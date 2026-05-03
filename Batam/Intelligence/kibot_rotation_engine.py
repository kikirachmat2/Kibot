#!/usr/bin/env python3
"""
KiBot Trinity - Sovereign Recovery & Rotation Engine (v7.5)
==========================================================
Advanced position optimization and distress recovery.
Enables "Smart Decisions" to swap losing positions for high-conviction winners.
"""

import os
import json
import logging
import time
from typing import Dict, Any, Optional

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

    def evaluate_rotation(self, 
                          active_pos: Dict[str, Any], 
                          new_signal: Dict[str, Any], 
                          market_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculates a rotation score (0-100).
        Handles both 'Profit Locking' and 'Distress Recovery'.
        """
        symbol = active_pos.get("symbol", active_pos.get("pairId", "UNKNOWN"))
        new_symbol = new_signal.get("symbol", new_signal.get("pairId", "UNKNOWN"))
        
        active_pnl = float(active_pos.get("pnl_pct", active_pos.get("profitPct", 0.0)))
        active_conf = float(active_pos.get("confidence", 50.0))
        new_conf = float(new_signal.get("confidence", 0.0))
        entry_time = float(active_pos.get("entry_time", time.time()))
        
        hours_active = (time.time() - entry_time) / 3600
        is_distressed = active_pnl < 0
        
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
            if new_conf < 85:
                return self._result(False, f"DISTRESS_VETO: New signal quality too low ({new_conf}) to cut loser", 0)
            
            conf_delta = new_conf - active_conf
            if conf_delta < self.config["distress_confidence_delta"]:
                return self._result(False, f"DISTRESS_VETO: Confidence delta insufficient (+{conf_delta}) for recovery swap", 0)

        # --- 2. SCORING ---
        
        # Base Score from Confidence Delta
        base_score = conf_delta * 1.5
        
        # Stagnancy Penalty
        stagnancy_score = 0
        if hours_active > self.config["stagnancy_threshold_hours"]:
            stagnancy_score = min(40, (hours_active - self.config["stagnancy_threshold_hours"]) * 10)
        
        # Distress Bonus: If in deep distress, we are MORE likely to rotate IF the new signal is elite
        distress_weight = 0
        if is_distressed and active_pnl <= self.config["distress_threshold_pct"]:
            distress_weight = 20 # Urgency to recover
        
        # Profit Reward: If winning, we are slightly more likely to rotate to lock profit
        profit_reward = 0
        if not is_distressed and active_pnl > 3.0:
            profit_reward = 15

        final_score = base_score + stagnancy_score + distress_weight + profit_reward
        
        # Threshold Check
        target_threshold = self.config["distress_gate_threshold"] if is_distressed else self.config["rotation_gate_threshold"]
        
        decision = final_score >= target_threshold
        
        mode = "DISTRESS_RECOVERY" if is_distressed else "PROFIT_OPTIMIZATION"
        rationale = (
            f"[{mode}] {symbol} -> {new_symbol}? "
            f"Score: {final_score:.1f}/{target_threshold}. "
            f"[PnL: {active_pnl:.2f}%, Conf Delta: {conf_delta:+.1f}, Stagnant: {stagnancy_score:.1f}]"
        )
        
        return self._result(decision, rationale, final_score)

    def _result(self, approved: bool, reason: str, score: float) -> Dict[str, Any]:
        return {
            "approved": approved,
            "reason": reason,
            "rotation_score": score,
            "engine_version": "7.5"
        }
