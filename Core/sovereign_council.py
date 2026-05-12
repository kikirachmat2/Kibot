from __future__ import annotations
import os, json, time, asyncio, logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from Core.Support.ki_vault import load_sovereign_env
from Core.Intelligence.kibot_ai_coordinator import query_ai
from Core.Intelligence.kibot_ai_search import AISearchService
from Core.sovereign_state import save_strategy, load_strategy, set_urgency, load_pnl_history

logger = logging.getLogger("SovereignCouncil")

class SovereignCouncil:
    """
    Sovereign Council of KiBot
    The supreme deliberation engine for both system integrity and trading directives.
    Uses the centralized AI Coordinator for robust, multi-provider intelligence.
    """
    def __init__(self):
        base_dir = Path(__file__).resolve().parent.parent
        self.state_dir = base_dir / "state"
        self.decision_log = self.state_dir / "council_decisions.jsonl"
        self.directive_log = self.state_dir / "council_directives.json"
        self.whatif_file = self.state_dir / "whatif_results.json"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # Thresholds
        self.CONFIDENCE_AUTO_THRESHOLD = 0.85
        self.RISK_LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        self.search_service = AISearchService(timeout=6)
        
        # Load environment
        load_sovereign_env()

    def _load_whatif_snapshot(self) -> Dict[str, Any]:
        if not self.whatif_file.exists():
            return {"pairsSimulated": 0, "topOpportunities": [], "results": {}}
        try:
            with open(self.whatif_file, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.warning(f"Failed to load what-if snapshot: {e}")
        return {"pairsSimulated": 0, "topOpportunities": [], "results": {}}

    def _whatif_edge_score(self, whatif_snapshot: Dict[str, Any]) -> float:
        results = whatif_snapshot.get("results") if isinstance(whatif_snapshot, dict) else {}
        if not isinstance(results, dict) or not results:
            return 0.0
        best = 0.0
        positive = 0
        for item in results.values():
            if not isinstance(item, dict):
                continue
            ev = float(item.get("expectedValue") or 0.0)
            if ev > best:
                best = ev
            if ev > 0:
                positive += 1
        return min(1.0, max(0.0, best * 40.0) + min(0.25, positive * 0.04))

    def _evidence_floor(self, evidence_bundle: Dict[str, Any], whatif_snapshot: Dict[str, Any]) -> float:
        coverage = float(evidence_bundle.get("coverage_score") or 0.0)
        catalyst = float(evidence_bundle.get("catalyst_score") or 0.0)
        track = float(evidence_bundle.get("track_record_score") or 0.0)
        risk = float(evidence_bundle.get("risk_penalty") or 0.0)
        whatif_edge = self._whatif_edge_score(whatif_snapshot)

        floor = 0.78
        floor -= min(0.08, coverage * 0.05)
        floor -= min(0.08, catalyst * 0.06)
        floor -= min(0.06, track * 0.04)
        floor -= min(0.10, whatif_edge * 0.08)
        floor += min(0.08, risk * 0.06)
        return max(0.68, min(0.90, round(floor, 3)))

    def _get_today_trade_activity(self) -> Dict[str, Any]:
        """Read today's trade activity so the council can avoid blind repetition."""
        try:
            from Core.Intelligence.kibot_learning_engine import get_engine

            engine = get_engine()
            closed_stats = engine.get_today_stats()
            activity = engine.get_today_activity() if hasattr(engine, "get_today_activity") else {}
            return {
                "entries": int(activity.get("entries", 0) or 0),
                "open": int(activity.get("open", 0) or 0),
                "closed": int(closed_stats.get("total", 0) or 0),
                "win_rate": float(closed_stats.get("win_rate", 0.5) or 0.5),
                "pnl_idr": float(closed_stats.get("pnl_idr", 0.0) or 0.0),
            }
        except Exception as e:
            logger.debug(f"Failed to load today trade activity: {e}")
            return {"entries": 0, "open": 0, "closed": 0, "win_rate": 0.5, "pnl_idr": 0.0}

    async def _build_trade_evidence(self, signals_context: Dict[str, Any]) -> Dict[str, Any]:
        signals = list(signals_context.get("signals") or [])
        targets = []
        seen = set()
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            symbol = str(sig.get("base_symbol") or sig.get("symbol") or "").upper().strip()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            targets.append(symbol)
        targets = targets[:3]

        if not targets:
            return {
                "targets": [],
                "coverage_score": 0.0,
                "catalyst_score": 0.0,
                "track_record_score": 0.0,
                "risk_penalty": 0.0,
                "sources": [],
                "notes": ["no target symbols available"],
            }

        evidence_rows: List[Dict[str, Any]] = []
        source_names = set()
        catalysts = 0
        red_flags = 0
        track_hits = 0
        track_total = 0

        async def gather_for_symbol(symbol: str) -> Dict[str, Any]:
            pair = f"{symbol.lower()}_idr"
            queries = [
                f"{symbol} crypto latest catalyst listing partnership exploit",
                f"{pair} track record volume trend Indodax",
                f"{symbol} site:coingecko.com crypto",
            ]
            tavily, serper, ddg, finnhub, brave, cryptopanic = await asyncio.gather(
                self.search_service.tavily_search_async(queries[0], search_depth="advanced"),
                self.search_service.serper_search_async(queries[1]),
                self.search_service.ddg_search_async(queries[2], max_results=3),
                self.search_service.finnhub_news_async(symbol.lower()),
                self.search_service.brave_search_async(queries[0]),
                self.search_service.cryptopanic_news_async("hot"),
            )
            return {
                "symbol": symbol,
                "pair": pair,
                "tavily": tavily or {},
                "serper": serper or {},
                "ddg": ddg or [],
                "finnhub": finnhub or [],
                "brave": brave or {},
                "cryptopanic": cryptopanic or [],
            }

        symbol_payloads = await asyncio.gather(*(gather_for_symbol(symbol) for symbol in targets))

        for payload in symbol_payloads:
            symbol = payload.get("symbol")
            pair = payload.get("pair")
            texts: List[str] = []
            row_sources = set()
            for row in list(payload.get("finnhub") or [])[:3]:
                if isinstance(row, dict):
                    source_names.add("finnhub")
                    row_sources.add("finnhub")
                    title = str(row.get("headline") or row.get("title") or "").strip()
                    if title:
                        texts.append(title)
            tavily = payload.get("tavily") or {}
            if tavily:
                source_names.add("tavily")
                row_sources.add("tavily")
                ans = str(tavily.get("answer") or "").strip()
                if ans:
                    texts.append(ans)
                for item in list(tavily.get("results") or [])[:2]:
                    if isinstance(item, dict):
                        txt = str(item.get("content") or item.get("title") or "").strip()
                        if txt:
                            texts.append(txt)
            serper = payload.get("serper") or {}
            if serper:
                source_names.add("serper")
                row_sources.add("serper")
                for item in list(serper.get("organic") or [])[:2]:
                    if isinstance(item, dict):
                        txt = str(item.get("snippet") or item.get("title") or "").strip()
                        if txt:
                            texts.append(txt)
            for item in list(payload.get("ddg") or [])[:2]:
                if isinstance(item, dict):
                    source_names.add("ddg")
                    row_sources.add("ddg")
                    txt = str(item.get("body") or item.get("title") or "").strip()
                    if txt:
                        texts.append(txt)
            brave = payload.get("brave") or {}
            if brave:
                source_names.add("brave")
                row_sources.add("brave")
                for item in list((brave.get("web") or {}).get("results") or [])[:2]:
                    if isinstance(item, dict):
                        txt = str(item.get("description") or item.get("title") or "").strip()
                        if txt:
                            texts.append(txt)
            for item in list(payload.get("cryptopanic") or [])[:3]:
                if isinstance(item, dict):
                    source_names.add("cryptopanic")
                    row_sources.add("cryptopanic")
                    title = str(item.get("title") or "").strip()
                    if title:
                        texts.append(title)

            combined = " ".join(texts).lower()
            catalyst_hit = any(key in combined for key in (
                "listing", "mainnet", "partnership", "upgrade", "launch", "integrat", "airdrop", "etf", "approval"
            ))
            exploit_hit = any(key in combined for key in (
                "hack", "exploit", "rug", "lawsuit", "ban", "delist", "halt", "outage"
            ))
            track_hit = any(key in combined for key in ("volume", "liquidity", "trend", "history", "record"))

            if catalyst_hit:
                catalysts += 1
            if exploit_hit:
                red_flags += 1
            if track_hit:
                track_hits += 1
            track_total += 1

            evidence_rows.append({
                "symbol": symbol,
                "pair": pair,
                "source_count": len(row_sources),
                "catalyst_hit": catalyst_hit,
                "risk_hit": exploit_hit,
                "track_hit": track_hit,
                "summary": texts[:6],
            })

        coverage_score = min(1.0, len(source_names) / 5.0)
        catalyst_score = min(1.0, catalysts / max(1, len(symbol_payloads)))
        track_record_score = min(1.0, track_hits / max(1, track_total))
        risk_penalty = min(1.0, red_flags / max(1, len(symbol_payloads)))

        return {
            "targets": targets,
            "coverage_score": round(coverage_score, 3),
            "catalyst_score": round(catalyst_score, 3),
            "track_record_score": round(track_record_score, 3),
            "risk_penalty": round(risk_penalty, 3),
            "sources": sorted(source_names),
            "evidence_rows": evidence_rows,
            "notes": [
                "broadened validation across Tavily, Serper, Brave, DDG, Finnhub, and CryptoPanic",
                "track record proxy uses repeated mentions of volume, liquidity, history, and trend",
            ],
        }

    async def deliberate_system(self, issue_context: Dict) -> Dict:
        """Handles system anomalies and self-healing logic (Watchman mode)."""
        logger.info(f"🏛️ Council deliberating system issue: {issue_context.get('type')}")
        snapshot = issue_context.get("snapshot", {})
        
        # 1. OBSERVATION (Watchman)
        obs_res = await query_ai("COUNCIL_WATCHMAN", {"snapshot": snapshot})
        if not obs_res or obs_res.get("status") == "NORMAL":
            if issue_context.get("type") != "EMERGENCY":
                return {"action": "NONE", "confidence": 1.0}

        # 2. STRATEGY (Strategist)
        strat_res = await query_ai("COUNCIL_STRATEGIST", {
            "context": issue_context,
            "diagnosis": obs_res
        })
        
        decision = {
            "type": "SYSTEM_ACTION",
            "issue": issue_context.get("type"),
            "action": strat_res.get("action", "NONE") if isinstance(strat_res, dict) else "NONE",
            "reasoning": strat_res.get("reasoning", "No AI response") if isinstance(strat_res, dict) else "ERROR",
            "confidence": strat_res.get("confidence", 0.0) if isinstance(strat_res, dict) else 0.0,
            "timestamp": time.time()
        }
        self._log_decision(decision)
        return decision

    async def run_strategic_planning(self, market_snapshot: Dict):
        """
        The 5-minute strategic debate.
        Inputs: Market Data, System Health.
        Output: New strategy parameters in active_strategy.json.
        """
        logger.info("🏛️ Council Strategic Session: Formulating new posture...")
        
        # 1. Gather Intelligence
        # We call System Engineer first for health check
        sys_stats = market_snapshot.get("system_stats", {}).get("BATAM_MASTER", {})
        cpu = sys_stats.get('cpu', 0)
        ram = sys_stats.get('ram', 0)
        
        # [SAFEGUARD] If usage is low, skip AI deliberation to avoid hallucinations
        if cpu < 80 and ram < 85:
            logging.info("🛡️ [SAFEGUARD] System resources low. Skipping AI health deliberation.")
            health = {"health_status": "STABLE", "action": "NONE", "reason": "System resources within safe limits (Auto-Stable)"}
        else:
            health_context = f"CPU: {cpu}%, MEM: {ram}%"
            health = await query_ai("SYSTEM_ENGINEER", {"netdata_snapshot": health_context})
        
        if health and health.get("action") == "PAUSE":
            set_urgency("EMERGENCY_PAUSE", health.get("reason"))
            return {"status": "PAUSED", "reason": health.get("reason")}

        # 2. Market Synthesis
        scout_res = await query_ai("MARKET_SCOUT", {"raw_scan_results": market_snapshot})
        sentiment = await query_ai("SENTIMENT_SYNTHESIZER", {"news_context": "Global Crypto Trends"})
        whatif_snapshot = self._load_whatif_snapshot()

        # [NEW V3.1] Forensic and Cross-Market Intelligence
        whale_intel = await query_ai("WHALE_WATCHER", {"orderbook_snapshot": market_snapshot.get("indodax")})
        bridge_alpha = await query_ai("CROSS_BRIDGE_STRATEGIST", {
            "indodax_data": market_snapshot.get("indodax"),
            "poly_data": market_snapshot.get("polymarket")
        })

        # 3. Final Strategic Decision (Strategy Dean)
        current = load_strategy()
        pnl_history = load_pnl_history()
        
        # [MIDNIGHT ORACLE LOGIC]
        from datetime import datetime
        now = datetime.now()
        # If between 23:45 and 00:00, force 'EXIT_ALL' mode
        is_midnight_approaching = (now.hour == 23 and now.minute >= 45)
        
        dean_res = await query_ai("STRATEGY_DEAN", {
            "market_data": scout_res,
            "system_health": health,
            "current_strategy": current,
            "sentiment": sentiment,
            "whale_intel": whale_intel,
            "bridge_alpha": bridge_alpha,
            "whatif_snapshot": whatif_snapshot,
            "recent_pnl": pnl_history,
            "is_midnight_approaching": is_midnight_approaching,
            "philosophy": "ORGANIZED_GREED" # Never satisfied
        })

        if not isinstance(dean_res, dict):
            logger.error(f"❌ [FATAL] AI Strategy Dean returned invalid response type: {type(dean_res)}")
            return {"status": "FAILED", "reason": "AI strategy generation failed - invalid type"}

        if dean_res:
            new_strategy = {
                "version": "3.0.0",
                "global_mode": dean_res.get("global_mode", "NEUTRAL"),
                "indodax": dean_res.get("indodax", current["indodax"]),
                "polymarket": dean_res.get("polymarket", current["polymarket"]),
                "last_updated": time.time()
            }
            save_strategy(new_strategy)
            logger.info(f"✅ Strategic Posture Updated: {new_strategy['global_mode']}")
            return {"status": "SUCCESS", "mode": new_strategy['global_mode']}
        
        return {"status": "FAILED", "reason": "AI strategy generation failed"}
        
    async def monitor_active_position(self, ticker: str, entry_price: float):
        """
        War Room mode for active trades.
        """
        logger.info(f"🛡️ Active Guardian: Protecting {ticker}...")
        res = await query_ai("ACTIVE_GUARDIAN", {"ticker": ticker, "entry_price": entry_price})
        
        if res and res.get("status") == "EXIT":
            # Force emergency exit by updating strategy or sending urgency
            logger.warning(f"🚨 GUARDIAN ORDERED EXIT: {ticker} - {res.get('reasoning')}")
            set_urgency("FORCE_EXIT", f"Guardian: {res.get('reasoning')}")

    async def deliberate_trading(self, signals_context: Dict) -> Dict:
        """
        [NEW V3.2] Trading Deliberation for MasterNode.
        Analyzes incoming signals and returns a formal mandate for execution.
        """
        logger.info(f"🏛️ Council Deliberating Trading Signals...")
        whatif_snapshot = self._load_whatif_snapshot()
        evidence_bundle = await self._build_trade_evidence(signals_context)
        today_trade_activity = self._get_today_trade_activity()
        signals_context = {
            **signals_context,
            "whatif_snapshot": whatif_snapshot,
            "evidence_bundle": evidence_bundle,
            "today_trade_activity": today_trade_activity,
        }
        
        # 1. Council Consensus
        # We use COUNCIL_SPEAKER to synthesize the final verdict from signals
        is_midnight = signals_context.get("is_midnight_approaching", False)
        decision = await query_ai("COUNCIL_SPEAKER", {
            **signals_context,
            "is_midnight_approaching": is_midnight
        })
        
        if not decision or not isinstance(decision, dict) or decision.get("is_fallback"):
            logger.warning(f"⚠️ Council failed to reach consensus or returned fallback/invalid: {type(decision)}")
            return {"status": "REJECTED", "reason": "No AI consensus or malformed response"}

        # 2. Add metadata and match source signal
        decision["timestamp"] = time.time()
        decision["whatif_snapshot"] = whatif_snapshot
        decision["evidence_bundle"] = evidence_bundle
        
        # Find matching signal from context for price/metadata parity
        signals = signals_context.get("signals", [])
        target_ticker = decision.get("ticker", "UNKNOWN").upper()
        
        source_signal = {}
        for s in signals:
            if s.get("ticker", "").upper() == target_ticker:
                source_signal = s
                break
        
        decision["source_signal"] = source_signal

        # 3. Determine Execution Status
        confidence_floor = self._evidence_floor(evidence_bundle, whatif_snapshot)
        decision["confidence_floor"] = confidence_floor
        decision["today_trade_activity"] = today_trade_activity
        decision.setdefault("learning_probe", False)
        decision.setdefault("trade_profile", "STANDARD")

        has_trade_today = int(today_trade_activity.get("entries", 0) or 0) > 0
        probe_floor = max(0.72, confidence_floor - 0.05)
        probe_ready = (
            decision.get("action") in ["BUY", "SELL"]
            and not has_trade_today
            and float(decision.get("confidence", 0) or 0) >= probe_floor
            and float(evidence_bundle.get("coverage_score", 0) or 0) >= 0.35
            and float(evidence_bundle.get("risk_penalty", 0) or 0) <= 0.6
            and self._whatif_edge_score(whatif_snapshot) > 0.0
        )

        if decision.get("action") in ["BUY", "SELL"] and decision.get("confidence", 0) >= confidence_floor:
            decision["status"] = "EXECUTING"
            decision["trade_profile"] = "STANDARD"
        elif decision.get("action") in ["BUY", "SELL"]:
            if probe_ready:
                decision["status"] = "EXECUTING"
                decision["learning_probe"] = True
                decision["trade_profile"] = "LEARNING_PROBE"
                decision["probe_confidence_floor"] = probe_floor
                decision["wait_reason"] = (
                    f"learning probe triggered: confidence {decision.get('confidence', 0):.3f} >= probe floor {probe_floor:.3f}"
                )
            else:
                decision["status"] = "WAIT"
                decision["wait_reason"] = (
                    f"confidence {decision.get('confidence', 0):.3f} below floor {confidence_floor:.3f}"
                )
        else:
            decision["status"] = "REJECTED"

        self._log_decision(decision)
        return decision

    def _log_decision(self, decision: Dict):
        try:
            with open(self.decision_log, "a") as f:
                f.write(json.dumps(decision) + "\n")
        except Exception as e:
            logger.error(f"Failed to log decision: {e}")

    def _save_directive(self, directive: Dict):
        try:
            with open(self.directive_log, "w") as f:
                json.dump(directive, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save directive: {e}")

    async def deliberate(self, issue_context: Dict) -> Dict:
        """Centralized deliberation entry point."""
        if issue_context.get("type") == "PROACTIVE_ORACLE":
             return await self.run_strategic_planning(issue_context.get("snapshot", {}))
        return await self.deliberate_system(issue_context)
