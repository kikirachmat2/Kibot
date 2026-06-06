import os
import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import json
import time
import socket
import logging
import asyncio
import inspect
from datetime import datetime, timezone
from typing import List, Dict, Any, Sequence
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from Core.Support.ki_config import KiConfig

logger = logging.getLogger("KiBotScanner")

try:
    from Core.Intelligence.leadlag_alpha import LeadLagAlphaEngine
except ImportError:
    LeadLagAlphaEngine = None

try:
    from Core.Intelligence.market_rotation import MarketRotationEngine
except ImportError:
    MarketRotationEngine = None

try:
    from Core.Web3.web3_opportunity_scanner import Web3OpportunityScanner
except ImportError:
    Web3OpportunityScanner = None

try:
    from Core.Scanner.market_wide_wave_scanner import MarketWideWaveScanner
except ImportError:
    MarketWideWaveScanner = None


class ScannerEngine:
    def __init__(self, scanners: Sequence[Any] | None = None, interval_s: int | None = None):
        self.interval_s = int(interval_s or os.getenv("SCAN_INTERVAL_S", "2"))
        self.poly_interval_s = int(os.getenv("POLY_SCAN_INTERVAL_S", "30"))
        self.scanners: List[Any] = list(scanners or self._build_scanners())
        self.direct_indodax_dispatch = os.getenv("KIBOT_SCANNER_DIRECT_INDODAX", "0").strip().lower() in {"1", "true", "yes", "on"}
        self.direct_polymarket_dispatch = False if KiConfig.INDODAX_ONLY else os.getenv("KIBOT_SCANNER_DIRECT_POLYMARKET", "0").strip().lower() in {"1", "true", "yes", "on"}
        
        # Now centralized on localhost (Batam Internal)
        self.target_host = "127.0.0.1"
        self.target_port = 9998
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        self.last_prices = {} # For Delta Filtering
        self.seq_id = 0
        self.is_running = True
        self._last_poly_scan = 0.0
        self._last_heatmap_refresh = 0.0
        self._heatmap_interval_s = float(os.getenv("KIBOT_HEATMAP_REFRESH_SEC", "60") or 60)
        self._last_web3_scan = 0.0
        self._web3_scan_interval_s = float(os.getenv("KIBOT_WEB3_SCAN_INTERVAL_SEC", "30") or 30)
        self._last_ai_trace_refresh = 0.0
        self._ai_trace_interval_s = float(os.getenv("KIBOT_AI_TRACE_REFRESH_SEC", "60") or 60)
        self._last_market_wide_scan = 0.0
        self._market_wide_scan_interval_s = float(os.getenv("KIBOT_MARKET_WIDE_SCAN_INTERVAL_SEC", "120") or 120)

        # LeadLag alpha engine setup
        self.leadlag_enabled = os.getenv("KIBOT_LEADLAG_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        if LeadLagAlphaEngine is not None and self.leadlag_enabled:
            self.leadlag_engine = LeadLagAlphaEngine()
            logger.info("✅ Lead-Lag Alpha Engine initialized in HFT Scanner.")
        else:
            self.leadlag_engine = None

        # Market Rotation Engine setup
        if MarketRotationEngine is not None:
            self.rotation_engine = MarketRotationEngine()
            logger.info("✅ Market Rotation Engine initialized in HFT Scanner.")
        else:
            self.rotation_engine = None

        if Web3OpportunityScanner is not None and KiConfig.SCANNER_ENABLE_WEB3:
            self.web3_scanner = Web3OpportunityScanner()
            logger.info("✅ Web3 Opportunity Scanner initialized in HFT Scanner.")
        else:
            self.web3_scanner = None

        if MarketWideWaveScanner is not None and not KiConfig.INDODAX_ONLY:
            self.market_wide_scanner = MarketWideWaveScanner()
            logger.info("✅ Market-Wide Wave Scanner initialized in HFT Scanner.")
        else:
            self.market_wide_scanner = None

        # Turbo Adaptive Mode setup
        self.scanner_turbo = os.getenv("KIBOT_SCANNER_TURBO", "true").strip().lower() in {"1", "true", "yes", "on", "auto"}
        self.fast_interval = float(os.getenv("KIBOT_SCANNER_FAST_INTERVAL", "0.1"))
        self.normal_interval = float(self.interval_s)
        self.slow_interval = float(os.getenv("KIBOT_SCANNER_SLOW_INTERVAL", "3.0"))
        self.cpu_soft_limit = float(os.getenv("KIBOT_CPU_SOFT_LIMIT", "70.0"))
        self.cpu_hard_limit = float(os.getenv("KIBOT_CPU_HARD_LIMIT", "90.0"))
        
        self.current_interval = self.normal_interval
        self.current_mode = "NORMAL"
        self.fast_cycles_remaining = 0

    def _extract_signals(self, res: Any) -> List[Dict[str, Any]]:
        if isinstance(res, dict):
            raw = res.get("signals", [])
            return raw if isinstance(raw, list) else []
        if isinstance(res, list):
            return res
        return []

    def _signal_uid(self, signal: Dict[str, Any]) -> str:
        """Build a stable UID per logical signal so delta filtering does not collapse distinct markets."""
        exchange = str(signal.get("exchange") or "UNKNOWN").upper().strip()
        symbol = str(signal.get("symbol") or signal.get("base_symbol") or "UNK").upper().strip()

        if exchange == "POLYMARKET":
            meta = signal.get("meta") if isinstance(signal.get("meta"), dict) else {}
            market_id = str(meta.get("market_id") or signal.get("market_id") or symbol).upper().strip()
            outcome_index = meta.get("outcome_index")
            outcome_suffix = f":{outcome_index}" if outcome_index is not None else ""
            return f"{exchange}:{market_id}{outcome_suffix}"

        if exchange == "INDODAX":
            return f"{exchange}:{symbol}"

        if exchange == "UNIVERSAL_LEAD":
            topic = str(signal.get("topic") or signal.get("keyword") or symbol).upper().strip()
            return f"{exchange}:{topic}"

        return f"{exchange}:{symbol}"

    def _normalize_price(self, exchange: str, signal: Dict[str, Any]) -> Any:
        if exchange == "INDODAX":
            raw_price = signal.get("price_idr", signal.get("price", 0))
        elif exchange == "POLYMARKET":
            raw_price = signal.get("price", 0)
        else:
            raw_price = signal.get("price_usdt", signal.get("price", 0))

        try:
            return round(float(raw_price), 8)
        except Exception:
            return raw_price

    def _build_scanners(self):
        """Builds default scanners if none provided."""
        scanners = []
        try:
            from Core.Scanner.indodax_market_scanner import IndodaxMarketScanner
            scanners.append(IndodaxMarketScanner())
            logger.info("✅ Indodax Market Scanner integrated (market-wide + Binance lead-lag).")
        except Exception as e:
            logger.error(f"⚠️ Failed to build Indodax Market scanner: {e}")
            try:
                from Core.Scanner.ki_indodax_smallcap_scanner import IndodaxSmallCapScanner
                scanners.append(IndodaxSmallCapScanner())
                logger.info("✅ Fallback Indodax SmallCap Scanner integrated.")
            except Exception as fallback_exc:
                logger.error(f"⚠️ Failed to build fallback Indodax scanner: {fallback_exc}")
            
        if KiConfig.INDODAX_ONLY:
            return scanners

        try:
            from Core.Scanner.ki_polymarket_full_scanner import PolymarketFullScanner
            scanners.append(PolymarketFullScanner())
            logger.info("✅ Polymarket Full Scanner integrated.")
        except Exception as e:
            logger.error(f"⚠️ Failed to build Polymarket scanner: {e}")

        if not KiConfig.SCANNER_ENABLE_UNIVERSAL:
            return scanners

        try:
            from Core.Scanner.ki_universal_leadlag_scanner import UniversalLeadLagScanner
            scanners.append(UniversalLeadLagScanner())
            logger.info("✅ Universal Lead-Lag Scanner (18+ Sources) integrated.")
        except Exception as e:
            logger.error(f"⚠️ Failed to build Universal scanner: {e}")
            
        return scanners

    def _scan_one(self, scanner: Any) -> Dict[str, Any]:
        exchange = str(getattr(scanner, "exchange", "UNKNOWN")).upper()
        signals = []
        try:
            collect = getattr(scanner, "collect_signals", None)
            if collect is None:
                return {"signals": []}

            if inspect.iscoroutinefunction(collect):
                res = asyncio.run(collect())
            else:
                res = collect()

            raw_signals = self._extract_signals(res)
            for s in raw_signals:
                if not isinstance(s, dict):
                    continue
                s["exchange"] = exchange
                uid = self._signal_uid(s)
                current_price = self._normalize_price(exchange, s)
                
                # DELTA FILTER: Skip jika harga sama persis
                if uid in self.last_prices and self.last_prices[uid] == current_price:
                    continue
                
                self.last_prices[uid] = current_price
                signals.append(s)
        except Exception as e:
            logger.debug(f"Scan error for {exchange}: {e}")
        return {"signals": signals}

    async def _dispatch(self, port: int, data: Dict[str, Any], secret: str) -> None:
        from Core.Support.ki_utils import sign_payload
        from Core.Support.ki_config import KiConfig
        payload = json.dumps({
            "data": data,
            "signature": sign_payload(data, secret)
        }).encode("utf-8")
        self.udp_sock.sendto(payload, (self.target_host, port))

    async def run_once_async(self) -> None:
        """Single scanning cycle."""
        self.universal_signals = []
        self.seq_id += 1
        started_at = time.time()
        from Core.Support.ki_config import KiConfig

        # ── § Lead-Lag Arbitrage Opportunities Evaluation ──
        leadlag_opportunities = []
        if self.leadlag_engine:
            try:
                leadlag_opportunities = await self.leadlag_engine.calculate_opportunities()
                # Persist leadlag_alpha.json in STATE_DIR
                from Core.Support.ki_config import STATE_DIR
                import tempfile
                
                state_path = Path(STATE_DIR) / "leadlag_alpha.json"
                state_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8",
                    dir=str(state_path.parent), delete=False, suffix=".tmp"
                )
                json.dump({
                    "seq_id": self.seq_id,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "opportunities": leadlag_opportunities
                }, tmp, ensure_ascii=False, default=str)
                tmp.flush()
                tmp.close()
                Path(tmp.name).replace(state_path)
            except Exception as e:
                logger.debug(f"[Scanner] LeadLag calculation/persist failed: {e}")

        # Evaluate CPU & Memory Telemetry for Adaptive Mode
        cpu_pct = 20.0
        mem_pct = 20.0
        try:
            import psutil
            cpu_pct = psutil.cpu_percent()
            mem_pct = psutil.virtual_memory().percent
        except Exception:
            pass
            
        if self.scanner_turbo:
            if cpu_pct >= self.cpu_hard_limit:
                self.current_interval = self.slow_interval
                self.current_mode = "SLOW"
                self.fast_cycles_remaining = 0
            elif cpu_pct >= self.cpu_soft_limit:
                self.current_interval = self.normal_interval
                self.current_mode = "NORMAL"
                self.fast_cycles_remaining = 0
            else:
                has_active_alpha = any(opp.get("trade_grade") in {"A", "B"} for opp in leadlag_opportunities)
                if has_active_alpha:
                    self.fast_cycles_remaining = 10
                    
                if self.fast_cycles_remaining > 0:
                    self.current_interval = self.fast_interval
                    self.current_mode = "FAST"
                    self.fast_cycles_remaining -= 1
                else:
                    self.current_interval = self.normal_interval
                    self.current_mode = "NORMAL"
        else:
            self.current_interval = self.normal_interval
            self.current_mode = "NORMAL"

        # Persist scanner_runtime.json in STATE_DIR
        try:
            from Core.Support.ki_config import STATE_DIR
            import tempfile
            runtime_path = Path(STATE_DIR) / "scanner_runtime.json"
            runtime_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8",
                dir=str(runtime_path.parent), delete=False, suffix=".tmp"
            )
            json.dump({
                "seq_id": self.seq_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": self.current_mode,
                "current_interval_s": self.current_interval,
                "cpu_percent": cpu_pct,
                "memory_percent": mem_pct,
                "fast_cycles_remaining": self.fast_cycles_remaining,
                "elapsed_ms": round((time.time() - started_at) * 1000, 2)
            }, tmp, ensure_ascii=False, default=str)
            tmp.flush()
            tmp.close()
            Path(tmp.name).replace(runtime_path)
        except Exception as e:
            logger.debug(f"[Scanner] scanner_runtime.json write failed: {e}")

        # Compute and persist optimal market rotation allocation
        if getattr(self, "rotation_engine", None):
            try:
                await self.rotation_engine.compute_optimal_allocation()
            except Exception as e:
                logger.debug(f"[Scanner] Market rotation allocation computation failed: {e}")

        selected_scanners = []
        for scanner in self.scanners:
            exchange = str(getattr(scanner, "exchange", "UNKNOWN")).upper()
            if exchange == "POLYMARKET":
                if started_at - self._last_poly_scan < self.poly_interval_s:
                    continue
                self._last_poly_scan = started_at
            selected_scanners.append(scanner)

        with ThreadPoolExecutor(max_workers=max(1, len(selected_scanners))) as executor:
            results = list(executor.map(self._scan_one, selected_scanners))
            
        # Group signals by destination
        indo_signals = []
        poly_signals = []
        
        for res in results:
            for s in res["signals"]:
                ex = s.get("exchange")
                if ex == "INDODAX":
                    indo_signals.append(s)
                elif ex == "POLYMARKET":
                    poly_signals.append(s)
                elif ex == "UNIVERSAL_LEAD":
                    if not hasattr(self, 'universal_signals'): self.universal_signals = []
                    self.universal_signals.append(s)

        # Append qualified lead-lag opportunities to indo_signals
        for opp in leadlag_opportunities:
            if opp.get("trade_grade") in {"A", "B"}:
                sig = {
                    "exchange": "INDODAX",
                    "source": "LEADLAG_ALPHA",
                    "symbol": opp["symbol"],
                    "price": opp["expected_net_pct"], # expected net yield proxy
                    "opportunity_score": opp["opportunity_score"],
                    "confidence": opp["confidence"],
                    "trade_grade": opp["trade_grade"],
                    "expected_net_pct": opp["expected_net_pct"],
                    "leadlag_pass": True,
                    "ts": int(started_at * 1000)
                }
                indo_signals.append(sig)

        from Core.Support.ki_utils import sign_payload
        secret = os.environ.get("KIBOT_SECRET")
        if not secret:
            logger.error("❌ CRITICAL: KIBOT_SECRET missing. Scanner will not dispatch signals.")
            return

        # Raw scanner signals are council input by default. Direct executor dispatch is
        # opt-in only so the Council cannot be bypassed by a misleading leaderboard pump.
        if indo_signals and self.direct_indodax_dispatch:
            data = {
                "seq_id": self.seq_id,
                "ts": int(started_at * 1000),
                "signals": indo_signals
            }
            await self._dispatch(KiConfig.INDO_SIGNAL_PORT, data, secret)
            logger.debug(f"[SCANNER] Seq:{self.seq_id} | Dispatched {len(indo_signals)} HMAC-signed INDO signals.")
        elif indo_signals:
            logger.debug(f"[SCANNER] Seq:{self.seq_id} | {len(indo_signals)} INDO signals routed to Council only.")

        # Dispatch Polymarket
        if poly_signals and self.direct_polymarket_dispatch:
            data = {
                "seq_id": self.seq_id,
                "ts": int(started_at * 1000),
                "signals": poly_signals
            }
            await self._dispatch(KiConfig.POLY_SIGNAL_PORT, data, secret)
            logger.debug(f"[SCANNER] Seq:{self.seq_id} | Dispatched {len(poly_signals)} HMAC-signed POLY signals.")
        elif poly_signals:
            logger.debug(f"[SCANNER] Seq:{self.seq_id} | {len(poly_signals)} POLY signals routed to Council only.")

        # NEW: Dispatch to MasterNode (Council) for high-level deliberation.
        # Universal lead-lag items are useful context, but they are not directly
        # executable. Do not wake Council for universal-only slates or it wastes
        # AI budget debating non-tradeable exchange names.
        universal_signals = getattr(self, 'universal_signals', [])
        all_signals = indo_signals + poly_signals + universal_signals
        tradeable_signals = indo_signals + poly_signals
        dispatch_signals = all_signals if tradeable_signals else []
        if dispatch_signals:
            data = {
                "type": "COUNCIL_SIGNAL_DATA",
                "signals": dispatch_signals,
                "ts": int(started_at * 1000)
            }
            await self._dispatch(9991, data, secret)
            logger.info(f"🧠 Dispatched {len(dispatch_signals)} HMAC-signed signals to Sovereign Council.")

        # Persist a compact, human/auditor-readable signal slate every cycle.
        # Even an empty slate is useful: dashboard/reporting can distinguish
        # "no candidates" from "scanner state is stale or missing".
        try:
            from Core.Support.ki_config import STATE_DIR
            from Core.Intelligence.decision_journal import log_scanner_candidates
            import tempfile

            ranked = sorted(
                all_signals,
                key=lambda s: float(s.get("opportunity_score") or s.get("confidence") or 0),
                reverse=True,
            )
            payload = {
                "seq_id": self.seq_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total": len(all_signals),
                "indodax_count": len(indo_signals),
                "polymarket_count": len(poly_signals),
                "universal_count": len(getattr(self, "universal_signals", [])),
                "top": ranked[:25],
            }
            state_path = Path(STATE_DIR) / "scanner_candidates.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8",
                dir=str(state_path.parent), delete=False, suffix=".tmp"
            )
            json.dump(payload, tmp, ensure_ascii=False, default=str)
            tmp.flush()
            tmp.close()
            Path(tmp.name).replace(state_path)
            if ranked:
                log_scanner_candidates(ranked[:25], context={"seq_id": self.seq_id})
        except Exception as _cand_err:
            logger.debug(f"[Scanner] scanner_candidates write failed: {_cand_err}")

        if started_at - self._last_heatmap_refresh >= self._heatmap_interval_s:
            self._last_heatmap_refresh = started_at
            try:
                from Core.Intelligence.market_heatmap import fetch_indodax_heatmap

                fetch_indodax_heatmap(persist=True, timeout=6.0)
            except Exception as _heatmap_err:
                logger.debug(f"[Scanner] heatmap refresh skipped: {_heatmap_err}")

        if self.web3_scanner and (started_at - self._last_web3_scan >= self._web3_scan_interval_s):
            self._last_web3_scan = started_at
            try:
                try:
                    from Core.Support.ki_config import STATE_DIR
                    web3_state = Path(STATE_DIR) / "web3_opportunities.json"
                    if web3_state.exists():
                        web3_state.touch()
                except Exception as _touch_err:
                    logger.debug(f"[Scanner] web3 heartbeat touch skipped: {_touch_err}")
                await self.web3_scanner.scan()
            except Exception as _web3_err:
                logger.debug(f"[Scanner] web3 opportunity scan skipped: {_web3_err}")

        if started_at - self._last_ai_trace_refresh >= self._ai_trace_interval_s:
            self._last_ai_trace_refresh = started_at
            try:
                from Core.Intelligence.kibot_ai_scout import AI_TRACE_FILE
                import tempfile

                trace_path = Path(AI_TRACE_FILE)
                trace_path.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "objective": "maximize_risk_adjusted_profit_for_boss",
                    "market_summary": "scanner heartbeat",
                    "best_action": "WAIT",
                    "venue": "indodax",
                    "reason": "scanner_heartbeat",
                    "confidence": 0.0,
                    "risk_status": "SCANNING",
                    "next_check_seconds": 60,
                }
                tmp = tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8",
                    dir=str(trace_path.parent), delete=False, suffix=".tmp"
                )
                json.dump(payload, tmp, ensure_ascii=False, default=str)
                tmp.flush()
                tmp.close()
                Path(tmp.name).replace(trace_path)
            except Exception as _ai_err:
                logger.debug(f"[Scanner] ai_decision_trace heartbeat skipped: {_ai_err}")

        if self.market_wide_scanner and (started_at - self._last_market_wide_scan >= self._market_wide_scan_interval_s):
            self._last_market_wide_scan = started_at
            try:
                await self.market_wide_scanner.scan()
            except Exception as _mw_err:
                logger.debug(f"[Scanner] market-wide wave scan skipped: {_mw_err}")

        # ── §17.2 Persist best Indodax signal for dashboard Signal Intel panel ──
        if indo_signals:
            try:
                from Core.Support.ki_config import STATE_DIR
                import tempfile
                best = max(
                    indo_signals,
                    key=lambda s: float(s.get("opportunity_score") or s.get("confidence") or 0)
                )
                payload = {
                    **best,
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                }
                state_path = Path(STATE_DIR) / "last_signal.json"
                state_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8",
                    dir=str(state_path.parent), delete=False, suffix=".tmp"
                )
                json.dump(payload, tmp, ensure_ascii=False, default=str)
                tmp.flush()
                tmp.close()
                Path(tmp.name).replace(state_path)
            except Exception as _sig_err:
                logger.debug(f"[Scanner] last_signal.json write failed: {_sig_err}")

    def run(self) -> None:
        logger.info(f"🚀 KiBot HFT Scanner Engine Started (dynamic adaptive interval).")
        async def _run_async():
            while self.is_running:
                t0 = time.time()
                try:
                    await self.run_once_async()
                except Exception as e:
                    logger.error(f"Scanner Runtime Error: {e}")
                elapsed = time.time() - t0
                await asyncio.sleep(max(0.05, float(self.current_interval) - elapsed))

        asyncio.run(_run_async())

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scanner = ScannerEngine()
    scanner.run()
