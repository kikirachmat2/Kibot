#!/usr/bin/env python3
"""
KiBot Trinity - Sovereign Recovery & Rotation Engine (v8.0)
==========================================================
Advanced position optimization, distress recovery, and regime-aware rotation.
"""

import os
import json
import logging
import time
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Intelligence Path Injection
_root = Path(__file__).resolve().parent.parent
sys.path.append(str(_root / "Indicators_Math"))
try:
    from kibot_learning_engine import get_engine as get_learning_engine
    from coin_universe_overlay import get_active_universe
except ImportError:
    get_learning_engine = lambda: None
    get_active_universe = lambda: {"sectors": {}}

logger = logging.getLogger("kibot.rotation")

class RotationEngine:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {
            "min_rotation_profit_pct": 0.5,    # Min profit to cover fees
            "distress_threshold_pct": -2.0,   # Position is considered "in distress"
            "stagnancy_threshold_hours": 2,   # Max 2 hours stagnation
            "min_confidence_delta": 15,       # Confidence gap for profit rotation
            "distress_confidence_delta": 25,  # Higher gap required to cut a loser
            "rotation_gate_threshold": 60,    # Base score to trigger
            "distress_gate_threshold": 75     # Harder to trigger for losers
        }
        self.universe = get_active_universe()

    def evaluate_rotation(self, 
                          active_pos: Dict[str, Any], 
                          new_signal: Dict[str, Any], 
                          market_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Rotation Engine v8.0 (Sovereign Intelligence)
        - Regime Aware: Sensitivity adjusts to BULL/BEAR/PANIC.
        - Sector Correlation Check: Avoids rotating within the same failing sector.
        - Bayesian Health Integration: Weights decisions by historical pair health.
        """
        symbol = active_pos.get("symbol", active_pos.get("pairId", "UNKNOWN"))
        new_symbol = new_signal.get("symbol", new_signal.get("pairId", "UNKNOWN"))
        regime = market_context.get("regime", "NORMAL").upper()
        
        active_pnl = float(active_pos.get("pnl_pct", active_pos.get("profitPct", 0.0)))
        active_conf = float(active_pos.get("confidence", 50.0))
        new_conf = float(new_signal.get("confidence", 0.0))
        entry_time = float(active_pos.get("entry_time", time.time()))
        
        hours_active = (time.time() - entry_time) / 3600
        is_distressed = active_pnl < 0
        
        # --- 0. SECTOR CORRELATION VETO ---
        # Refresh universe periodically
        if time.time() % 300 < 30: # Check refresh every 5 mins
            self.universe = get_active_universe()

        sectors = self.universe.get("sectors", {})
        old_sector = sectors.get(symbol, "unknown")
        new_sector = sectors.get(new_symbol, "unknown")
        
        # PARANOID VETO: If in PANIC, we assume correlation if sector is unknown or identical
        if "PANIC" in regime:
            if old_sector == new_sector:
                return self._result(False, f"CORRELATION_VETO: Both in {old_sector} during {regime}", 0)
            if old_sector == "unknown" or new_sector == "unknown":
                return self._result(False, f"CORRELATION_VETO: Missing sector data during {regime}. Veto for safety.", 0)

        # --- 1. GATES ---
        
        # PROFIT ROTATION GATES
        if not is_distressed:
            if active_pnl < self.config["min_rotation_profit_pct"]:
                return self._result(False, f"PROFIT_ROTATION: Below fee safety ({active_pnl}%)", 0)
            
            conf_delta = new_conf - active_conf
            if conf_delta < self.config["min_confidence_delta"]:
                return self._result(False, f"PROFIT_ROTATION: Confidence delta too low (+{conf_delta})", 0)
        
        # DISTRESS ROTATION GATES (Recovery Mode)
        else:
            # We only cut losers for ELITE signals (Confidence > 85)
            min_elite = 85
            if "BEARISH" in regime or "PANIC" in regime: min_elite = 92
            
            if new_conf < min_elite:
                return self._result(False, f"DISTRESS_VETO: New signal quality too low ({new_conf}) for {regime} regime", 0)
            
            conf_delta = new_conf - active_conf
            if conf_delta < self.config["distress_confidence_delta"]:
                return self._result(False, f"DISTRESS_VETO: Confidence delta insufficient (+{conf_delta}) for recovery", 0)

        # --- 2. SCORING ---
        
        # Base Score from Confidence Delta
        base_score = conf_delta * 1.5
        
        # Bayesian Health Bonus/Penalty
        learn = get_learning_engine()
        health_weight = 0
        if learn:
            old_health = learn.get_pair_health(symbol)
            new_health = learn.get_pair_health(new_symbol)
            health_weight = (new_health - old_health) * 30 # Scale health diff to 0-30 points
        
        # Stagnancy Penalty
        stagnancy_score = 0
        if hours_active > self.config["stagnancy_threshold_hours"]:
            stagnancy_score = min(40, (hours_active - self.config["stagnancy_threshold_hours"]) * 10)
        
        # Distress Bonus
        distress_weight = 0
        if is_distressed and active_pnl <= self.config["distress_threshold_pct"]:
            distress_weight = 20
        
        final_score = base_score + health_weight + stagnancy_score + distress_weight
        
        # Regime Sensitivity Adjustment
        target_threshold = self.config["distress_gate_threshold"] if is_distressed else self.config["rotation_gate_threshold"]
        if "BULLISH" in regime: target_threshold -= 10 # More aggressive
        if "PANIC" in regime: target_threshold += 20 # Extreme caution

        decision = final_score >= target_threshold
        
        mode = "DISTRESS_RECOVERY" if is_distressed else "PROFIT_OPTIMIZATION"
        rationale = (
            f"[{mode}][v8] {symbol}({old_sector}) -> {new_symbol}({new_sector})? "
            f"Score: {final_score:.1f}/{target_threshold}. [Regime: {regime}]"
        )
        
        return self._result(decision, rationale, final_score)

    def _result(self, approved: bool, reason: str, score: float) -> Dict[str, Any]:
        return {
            "approved": approved,
            "reason": reason,
            "rotation_score": score,
            "engine_version": "8.0"
        }
