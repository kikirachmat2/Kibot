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
from datetime import datetime, timezone
from typing import List, Dict, Any, Sequence
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("KiBotScanner")

class ScannerEngine:
    def __init__(self, scanners: Sequence[Any] | None = None, interval_s: int | None = None):
        self.interval_s = int(interval_s or os.getenv("SCAN_INTERVAL_S", "2"))
        self.poly_interval_s = int(os.getenv("POLY_SCAN_INTERVAL_S", "30"))
        self.scanners: List[Any] = list(scanners or self._build_scanners())
        self.direct_indodax_dispatch = os.getenv("KIBOT_SCANNER_DIRECT_INDODAX", "0").strip().lower() in {"1", "true", "yes", "on"}
        self.direct_polymarket_dispatch = os.getenv("KIBOT_SCANNER_DIRECT_POLYMARKET", "0").strip().lower() in {"1", "true", "yes", "on"}
        
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
            from Core.Scanner.ki_indodax_smallcap_scanner import IndodaxSmallCapScanner
            scanners.append(IndodaxSmallCapScanner())
            logger.info("✅ Indodax SmallCap Scanner integrated.")
        except Exception as e:
            logger.error(f"⚠️ Failed to build Indodax scanner: {e}")
            
        try:
            from Core.Scanner.ki_polymarket_full_scanner import PolymarketFullScanner
            scanners.append(PolymarketFullScanner())
            logger.info("✅ Polymarket Full Scanner integrated.")
        except Exception as e:
            logger.error(f"⚠️ Failed to build Polymarket scanner: {e}")

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

            if asyncio.iscoroutinefunction(collect):
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
        logger.info(f"🚀 KiBot HFT Scanner Engine Started ({self.interval_s}s interval).")
        async def _run_async():
            while self.is_running:
                t0 = time.time()
                try:
                    await self.run_once_async()
                except Exception as e:
                    logger.error(f"Scanner Runtime Error: {e}")
                elapsed = time.time() - t0
                await asyncio.sleep(max(0.05, float(self.interval_s) - elapsed))

        asyncio.run(_run_async())

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scanner = ScannerEngine()
    scanner.run()
