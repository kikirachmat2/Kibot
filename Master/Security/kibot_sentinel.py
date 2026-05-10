#!/usr/bin/env python3
"""
KiBot Trade Sentinel
====================
Real-time anomaly detection for trade orders.
Monitors velocity (trades/losses per minute) and price deviations.
"""

import time
from collections import deque
from typing import Dict, List, Tuple, Optional

class TradeSentinel:
    def __init__(self, 
                 max_trades_per_min: int = 5, 
                 max_loss_pct_per_min: float = 2.0,
                 max_price_deviation_pct: float = 5.0):
        
        self.max_trades_per_min = max_trades_per_min
        self.max_loss_pct_per_min = max_loss_pct_per_min
        self.max_price_deviation_pct = max_price_deviation_pct
        
        # Windows: list of (timestamp, value)
        self.trade_window = deque()
        self.loss_window = deque()
        
        self.is_restricted = False
        self.restriction_reason = ""

    def _cleanup_window(self, window: deque, duration_sec: int = 60):
        now = time.time()
        while window and (now - window[0][0]) > duration_sec:
            window.popleft()

    def check_order(self, 
                    pair: str, 
                    side: str, 
                    price: float, 
                    market_mid_price: float, 
                    estimated_loss_pct: float = 0.0) -> Tuple[bool, str]:
        """
        Main entry point for order safety check.
        Returns (is_safe, reason).
        """
        if self.is_restricted:
            return False, f"Sentinel Active Restriction: {self.restriction_reason}"

        now = time.time()
        self._cleanup_window(self.trade_window)
        self._cleanup_window(self.loss_window)

        # 1. Velocity: Trade Frequency
        if len(self.trade_window) >= self.max_trades_per_min:
            self.is_restricted = True
            self.restriction_reason = f"Velocity Breach: {len(self.trade_window)} trades in 60s"
            return False, self.restriction_reason

        # 2. Velocity: Loss Accumulation
        current_min_loss = sum(l[1] for l in self.loss_window)
        if (current_min_loss + estimated_loss_pct) > self.max_loss_pct_per_min:
            self.is_restricted = True
            self.restriction_reason = f"Loss Velocity Breach: {current_min_loss + estimated_loss_pct:.2f}% loss in 60s"
            return False, self.restriction_reason

        # 3. Price Anomaly: Deviation from Mid-Price
        if market_mid_price > 0:
            deviation = abs(price - market_mid_price) / market_mid_price * 100
            if deviation > self.max_price_deviation_pct:
                return False, f"Price Anomaly: Order price {price} deviates {deviation:.2f}% from market mid {market_mid_price}"

        return True, "SAFE"

    def register_trade(self, success: bool, loss_pct: float = 0.0):
        """Update window stats after a trade attempt."""
        now = time.time()
        if success:
            self.trade_window.append((now, 1))
        
        if loss_pct > 0:
            self.loss_window.append((now, loss_pct))

    def reset(self):
        self.is_restricted = False
        self.restriction_reason = ""
        self.trade_window.clear()
        self.loss_window.clear()

# Singleton
_sentinel = TradeSentinel()

def get_sentinel():
    return _sentinel
