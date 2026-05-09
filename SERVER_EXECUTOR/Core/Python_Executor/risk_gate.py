#!/usr/bin/env python3
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger("RiskGate")

class RiskGate:
    """
    Sovereign Risk Guard.
    Prevents execution of signals that violate safety parameters.
    """
    def __init__(self, config: Optional[Dict] = None):
        # Default safety thresholds
        self.config = config or {
            "max_slippage_pct": 1.5,
            "min_order_notional_idr": 25000,
            "max_order_notional_idr": 5000000,
            "max_active_positions": 5,
            "blacklist": ["USDT_IDR"] # Prevent accidental recursive stablecoin loops
        }

    def validate_signal(self, signal: Dict, balance_idr: float, active_positions_count: int) -> Tuple[bool, str]:
        """
        Validates a trade signal against risk parameters.
        @return (is_valid, reason)
        """
        symbol = signal.get("symbol", "UNKNOWN").upper()
        price = float(signal.get("price", 0))
        side = signal.get("side", "BUY").upper()
        
        # 1. Basic sanity check
        if symbol == "UNKNOWN" or price <= 0:
            return False, "Invalid symbol or price"

        # 2. Blacklist check
        if symbol in self.config["blacklist"]:
            return False, f"Symbol {symbol} is blacklisted"

        # 3. Position limit check (only for BUY)
        if side == "BUY" and active_positions_count >= self.config["max_active_positions"]:
            return False, f"Max positions reached ({self.config['max_active_positions']})"

        # 4. Notional value check
        # For now, we assume a fixed budget if not specified
        budget = float(signal.get("budget_idr", self.config["min_order_notional_idr"]))
        
        if budget < self.config["min_order_notional_idr"]:
            return False, f"Order too small (Rp{budget} < Rp{self.config['min_order_notional_idr']})"
        
        if budget > self.config["max_order_notional_idr"]:
            return False, f"Order too large (Rp{budget} > Rp{self.config['max_order_notional_idr']})"

        # 5. Balance check
        if side == "BUY" and balance_idr < budget:
            return False, f"Insufficient IDR balance (Need Rp{budget}, have Rp{balance_idr})"

        # 6. Market Condition Check (Simulated for now)
        # We can add more advanced checks like bid/ask spread if provided in the signal meta
        meta = signal.get("meta", {})
        spread = float(meta.get("spread_pct", 0))
        if spread > self.config["max_slippage_pct"]:
             return False, f"Spread too wide ({spread}% > {self.config['max_slippage_pct']}%)"

        return True, "APPROVED"

    def calculate_amount(self, symbol: str, price: float, budget_idr: float) -> float:
        """Calculates the amount of coin to buy based on budget and price."""
        # Simple division. In production, we'd adjust for decimal precision per coin.
        return round(budget_idr / price, 8)
