import json
from pathlib import Path
from datetime import datetime, timedelta

class CouncilDataAggregator:
    """
    Council Data Aggregator
    Consolidates data from across the KiBot ecosystem to provide context for the Trading Council sessions.
    
    Data sources:
    - FastPathLogger (Signal History)
    - WhatIfTracker (Audit Results)
    - KiBotMaster State (Portfolio, Mesh Health)
    - Market Sentiment (Brain)
    """
    def __init__(self, master_node):
        self.master = master_node
        base_dir = Path(__file__).resolve().parent.parent
        self.fast_path_log = base_dir / "Logs" / "fast_path_signals.jsonl"
        self.what_if_log = base_dir / "Logs" / "what_if_analysis.json"

    def get_debate_context(self, tier="TIER_1_SYNC"):
        """
        Builds a comprehensive data snapshot for a council session.
        """
        rejection_stats = self._get_fast_path_stats()
        missed_opps = self._get_missed_opportunities()
        portfolio = self._get_portfolio_snapshot()
        market = self._get_market_context()
        
        # Collect unique pairs from audit
        unique_pairs = set()
        for opp in missed_opps:
            unique_pairs.add(opp.get("symbol"))
            
        context = {
            "session_tier": tier,
            "timestamp": datetime.now().isoformat(),
            "philosophy": {
                "core": "Sedikit Demi Sedikit, Lama-Lama Jadi Bukit",
                "rules": [
                    "Capital preservation first",
                    "Profit probability > 85%",
                    "Early TP at 0.5%"
                ]
            },
            "market_context": market,
            "portfolio_state": portfolio,
            "audit_data": {
                "rejection_analysis": rejection_stats,
                "missed_opportunities": missed_opps
            },
            "pair_memory": self._get_pair_memory(list(unique_pairs)),
            "council_history": self._get_council_history(),
            "system_health": self.master.last_state.get("mesh_nodes", {})
        }
        return context

    def _get_pair_memory(self, signal_pairs: list) -> dict:
        memory = {}
        try:
            from Intelligence.kibot_learning_engine import get_engine
            engine = get_engine()
            for pair in signal_pairs:
                # Basic health and stats
                memory[pair] = engine.get_pair_stats(pair)
        except Exception:
            pass
        return memory

    def _get_council_history(self) -> list:
        history = []
        try:
            base_dir = Path(__file__).resolve().parent.parent
            path = base_dir / "Logs" / "council_directives.json"
            if path.exists():
                with open(path, "r") as f:
                    directives = json.load(f)
                    # Return last 3 directives for context
                    history = directives[-3:] if isinstance(directives, list) else []
        except Exception:
            pass
        return history

    def _get_fast_path_stats(self, hours=24):
        """Analyzes recent signal rejections."""
        stats = {"total": 0, "vetoed": 0, "math_skipped": 0, "approved": 0, "reasons": {}}
        cutoff = datetime.now() - timedelta(hours=hours)
        
        if not self.fast_path_log.exists():
            return stats
            
        try:
            with open(self.fast_path_log, "r") as f:
                for line in f:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry["timestamp"])
                    if ts < cutoff: continue
                    
                    stats["total"] += 1
                    status = entry["status"]
                    if status == "APPROVED": stats["approved"] += 1
                    elif status == "VETOED": stats["vetoed"] += 1
                    elif status == "MATH_SKIP": stats["math_skipped"] += 1
                    
                    reason = entry["reason"]
                    stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1
        except Exception as e:
            print(f"ERROR [Aggregator]: Rejection analysis failed: {e}")
            
        return stats

    def _get_missed_opportunities(self):
        """Extracts significant missed gains from what-if analysis."""
        opportunities = []
        if not self.what_if_log.exists():
            return opportunities
            
        try:
            with open(self.what_if_log, "r") as f:
                data = json.load(f)
                for tid, track in data.items():
                    # Only report opportunities that gained > 1% but were rejected
                    if track.get("max_gain_pct", 0) > 1.0:
                        opportunities.append({
                            "symbol": track["symbol"],
                            "reason": track["reason"],
                            "gain_missed": f"{track['max_gain_pct']:.2f}%",
                            "entry_price": track["entry_price"]
                        })
        except Exception as e:
            print(f"ERROR [Aggregator]: Missed opportunity analysis failed: {e}")
            
        return sorted(opportunities, key=lambda x: x["gain_missed"], reverse=True)[:5]

    def _get_portfolio_snapshot(self):
        """Gets current holdings and PnL from the master node."""
        # Use master's last_state or direct indodax proxy data if available
        return self.master.last_state.get("portfolio", {
            "equity_idr": 0,
            "daily_pnl": "0.0%",
            "active_positions": []
        })

    def _get_market_context(self):
        """Gets market mood and global regime."""
        mood = getattr(self.master, "market_mood", "NEUTRAL")
        # Attempt to get deeper context from Brain snapshot if available
        brain_snap = {}
        if hasattr(self.master, "brain") and self.master.brain:
            if hasattr(self.master.brain, "snapshot") and callable(self.master.brain.snapshot):
                brain_snap = self.master.brain.snapshot()
            elif isinstance(self.master.brain, dict):
                brain_snap = self.master.brain
            
        return {
            "mood": mood,
            "regime": brain_snap.get("market_pulse", {}).get("risk_bias", "UNKNOWN"),
            "fear_greed": brain_snap.get("fear_greed", "N/A")
        }
