import logging
import json
import os
from datetime import date
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger("RiskGate")

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
RISK_STATE_FILE = STATE_DIR / "risk_state.json"

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
            "max_daily_loss_pct": 1.5, # 1.5% Max Daily Loss
            "blacklist": ["USDT_IDR"] 
        }
        self.daily_pnl = 0.0
        self.last_reset_date = str(date.today())
        self._load_state()

    def _load_state(self):
        if RISK_STATE_FILE.exists():
            try:
                with open(RISK_STATE_FILE, "r") as f:
                    state = json.load(f)
                    if state.get("last_reset_date") == str(date.today()):
                        self.daily_pnl = state.get("daily_pnl", 0.0)
                    else:
                        self.daily_pnl = 0.0
                        self.last_reset_date = str(date.today())
                        self._save_state()
            except Exception as e:
                logger.error(f"Failed to load risk state: {e}")

    def _save_state(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(RISK_STATE_FILE, "w") as f:
                json.dump({
                    "daily_pnl": self.daily_pnl,
                    "last_reset_date": self.last_reset_date
                }, f)
        except Exception as e:
            logger.error(f"Failed to save risk state: {e}")

    def update_pnl(self, pnl_amount: float):
        """Update daily PnL and persist state."""
        self._check_reset()
        self.daily_pnl += pnl_amount
        self._save_state()
        logger.info(f"💰 Daily PnL Updated: {self.daily_pnl:.2f} IDR")

    def _check_reset(self):
        today = str(date.today())
        if self.last_reset_date != today:
            logger.info("♻️ New day detected. Resetting daily PnL.")
            self.daily_pnl = 0.0
            self.last_reset_date = today
            self._save_state()

    def validate_signal(self, signal: Dict, balance_idr: float, active_positions_count: int) -> Tuple[bool, str]:
        """
        Validates a trade signal against risk parameters.
        @return (is_valid, reason)
        """
        self._check_reset()
        
        # 0. Daily Loss Check
        max_loss = balance_idr * (self.config["max_daily_loss_pct"] / 100)
        if self.daily_pnl < -max_loss:
            return False, f"Daily loss limit reached ({self.daily_pnl:.2f} < -{max_loss:.2f})"

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
        budget = float(signal.get("budget_idr", self.config["min_order_notional_idr"]))
        
        if budget < self.config["min_order_notional_idr"]:
            return False, f"Order too small (Rp{budget} < Rp{self.config['min_order_notional_idr']})"
        
        if budget > self.config["max_order_notional_idr"]:
            return False, f"Order too large (Rp{budget} > Rp{self.config['max_order_notional_idr']})"

        # 5. Balance check
        if side == "BUY" and balance_idr < budget:
            return False, f"Insufficient IDR balance (Need Rp{budget}, have Rp{balance_idr})"

        # 6. Market Condition Check
        meta = signal.get("meta", {})
        spread = float(meta.get("spread_pct", 0))
        if spread > self.config["max_slippage_pct"]:
             return False, f"Spread too wide ({spread}% > {self.config['max_slippage_pct']}%)"

        return True, "APPROVED"

    def calculate_amount(self, symbol: str, price: float, budget_idr: float) -> float:
        """Calculates the amount of coin to buy based on budget and price."""
        return round(budget_idr / price, 8)
