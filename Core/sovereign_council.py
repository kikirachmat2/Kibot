import os, json, time, asyncio, logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from Core.Support.ki_vault import load_sovereign_env
from Core.Intelligence.kibot_ai_coordinator import query_ai
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
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # Thresholds
        self.CONFIDENCE_AUTO_THRESHOLD = 0.85
        self.RISK_LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        
        # Load environment
        load_sovereign_env()

    async def deliberate_system(self, issue_context: Dict) -> Dict:
        """Handles system anomalies and self-healing logic (Watchman mode)."""
        logger.info(f"🏛️ Council deliberating system issue: {issue_context.get('type')}")
        snapshot = issue_context.get("snapshot", {})
        
        # 1. OBSERVATION (Watchman)
        obs_res = query_ai("COUNCIL_WATCHMAN", {"snapshot": snapshot})
        if not obs_res or obs_res.get("status") == "NORMAL":
            if issue_context.get("type") != "EMERGENCY":
                return {"action": "NONE", "confidence": 1.0}

        # 2. STRATEGY (Strategist)
        strat_res = query_ai("COUNCIL_STRATEGIST", {
            "context": issue_context,
            "diagnosis": obs_res
        })
        
        decision = {
            "type": "SYSTEM_ACTION",
            "issue": issue_context.get("type"),
            "action": strat_res.get("action", "NONE") if strat_res else "NONE",
            "reasoning": strat_res.get("reasoning", "No AI response") if strat_res else "ERROR",
            "confidence": strat_res.get("confidence", 0.0) if strat_res else 0.0,
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
        health = query_ai("SYSTEM_ENGINEER", {"netdata_snapshot": "CPU: 20%, MEM: 40%"}) # Mock data
        if health and health.get("action") == "PAUSE":
            set_urgency("EMERGENCY_PAUSE", health.get("reason"))
            return

        # 2. Market Synthesis
        scout_res = query_ai("MARKET_SCOUT", {"raw_scan_results": market_snapshot})
        sentiment = query_ai("SENTIMENT_SYNTHESIZER", {"news_context": "Global Crypto Trends"})
        
        # [NEW V3.1] Forensic and Cross-Market Intelligence
        whale_intel = query_ai("WHALE_WATCHER", {"orderbook_snapshot": market_snapshot.get("indodax")})
        bridge_alpha = query_ai("CROSS_BRIDGE_STRATEGIST", {
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
        
        dean_res = query_ai("STRATEGY_DEAN", {
            "market_data": scout_res,
            "system_health": health,
            "current_strategy": current,
            "sentiment": sentiment,
            "whale_intel": whale_intel,
            "bridge_alpha": bridge_alpha,
            "recent_pnl": pnl_history,
            "is_midnight_approaching": is_midnight_approaching,
            "philosophy": "ORGANIZED_GREED" # Never satisfied
        })

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
        
    async def monitor_active_position(self, ticker: str, entry_price: float):
        """
        War Room mode for active trades.
        """
        logger.info(f"🛡️ Active Guardian: Protecting {ticker}...")
        res = query_ai("ACTIVE_GUARDIAN", {"ticker": ticker, "entry_price": entry_price})
        
        if res and res.get("status") == "EXIT":
            # Force emergency exit by updating strategy or sending urgency
            logger.warning(f"🚨 GUARDIAN ORDERED EXIT: {ticker} - {res.get('reasoning')}")
            set_urgency("FORCE_EXIT", f"Guardian: {res.get('reasoning')}")

    async def deliberate_trading(self, context: Dict) -> Dict:
        """Legacy wrapper for compatibility, redirects to Strategy loop."""
        return await self.run_strategic_planning(context)

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
        """Backward compatibility for deliberate_system."""
        return await self.deliberate_system(issue_context)
