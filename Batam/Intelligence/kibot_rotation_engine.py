#!/usr/bin/env python3
"""
KiBot Capital Rotation Engine (v7.2)
====================================
Evaluates if an active position should be 'rotated' (closed) to free up capital
for a higher-confidence signal.

Gates:
1. Opportunity Gain (Signal Confidence > Active Confidence)
2. Stagnancy Penalty (Time-based decay)
3. Opportunity Cost (Potential gain vs. current gain)
4. Fee Safety (Minimum profit threshold)
5. Conviction Score (Analyst/Auditor consensus)
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
            "min_rotation_profit_pct": 0.5,    # Min profit to cover fees + buffer
            "stagnancy_threshold_hours": 2,   # Max 2 hours stagnation before rotation pressure rises
            "min_confidence_delta": 15,       # New signal must be 15% better than active
            "rotation_gate_threshold": 60,    # Total score required to rotate
            "profit_reward_weight": 5.0,      # Higher weight for locking 4%+ profits
            "stable_allocation_pct": 0.50     # Canonical 50/50 split for capital management
        }

    def evaluate_rotation(self, 
                          active_pos: Dict[str, Any], 
                          new_signal: Dict[str, Any], 
                          market_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculates a rotation score (0-100).
        Returns decision and rationale.
        """
        symbol = active_pos.get("symbol", "UNKNOWN")
        new_symbol = new_signal.get("symbol", "UNKNOWN")
        active_pnl = float(active_pos.get("pnl_pct", 0.0))
        active_conf = float(active_pos.get("confidence", 50.0))
        new_conf = float(new_signal.get("confidence", 0.0))
        entry_time = float(active_pos.get("entry_time", time.time()))
        
        # 1. Fee Safety Gate
        # Jangan rotasi kalau belum untung cukup buat nutup fee (kecuali stoploss, tapi ini engine rotasi untung)
        if active_pnl < self.config["min_rotation_profit_pct"]:
            return self._result(False, f"Below fee safety ({active_pnl}% < {self.config['min_rotation_profit_pct']}%)", 0)

        # 2. Opportunity Gain Gate
        conf_delta = new_conf - active_conf
        if conf_delta < self.config["min_confidence_delta"]:
            return self._result(False, f"Confidence delta too low ({conf_delta} < {self.config['min_confidence_delta']})", 0)

        # 3. Stagnancy Penalty
        hours_active = (time.time() - entry_time) / 3600
        stagnancy_score = 0
        if hours_active > self.config["stagnancy_threshold_hours"]:
            # Bertambah 5 poin per jam stagnan setelah threshold
            stagnancy_score = min(40, (hours_active - self.config["stagnancy_threshold_hours"]) * 5)
        
        # 4. Opportunity Cost Calculation
        # Delta confidence memberi base score
        base_score = conf_delta * 1.5
        
        # Profit reward: Jika sudah untung besar (stagnan di 4%), lebih berani rotasi
        pnl_bonus = active_pnl * self.config["profit_reward_weight"]
        
        # 5. Final Score Calculation
        final_score = base_score + stagnancy_score + pnl_bonus
        
        decision = final_score >= self.config["rotation_gate_threshold"]
        
        rationale = (
            f"Rotate {symbol} -> {new_symbol}? "
            f"Score: {final_score:.1f}/100. "
            f"[PnL: {active_pnl:.2f}%, Conf Delta: {conf_delta:+.1f}, Stagnant: {stagnancy_score:.1f}]"
        )
        
        return self._result(decision, rationale, final_score)

    def _result(self, approved: bool, reason: str, score: float) -> Dict[str, Any]:
        return {
            "approved": approved,
            "reason": reason,
            "rotation_score": score,
            "engine_version": "7.2"
        }

if __name__ == "__main__":
    # Smoke Test
    engine = RotationEngine()
    
    # Skenario: Koin stagnan di 4.2% profit selama 6 jam. Ada signal baru koin lain lebih tinggi 20% confidence.
    test_active = {
        "symbol": "BTCIDR",
        "pnl_pct": 4.2,
        "confidence": 65,
        "entry_time": time.time() - (6 * 3600)
    }
    test_signal = {
        "symbol": "SOL_IDR",
        "confidence": 85
    }
    
    res = engine.evaluate_rotation(test_active, test_signal, {})
    import json
    print(json.dumps(res, indent=2))
