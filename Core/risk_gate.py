import logging
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from Core.Support.ki_config import WIB

logger = logging.getLogger("RiskGate")

# Configuration
STATE_DIR = Path(__file__).resolve().parent.parent / "state"
RISK_STATE_FILE = STATE_DIR / "risk_state.json"


def _today_wib() -> str:
    """Business day boundary follows WIB, not the server's UTC clock."""
    return str(datetime.now(WIB).date())

class RiskGate:
    """
    Sovereign Risk Guard
    ====================
    V3.5: "Absolute Liberty"
    Ensures total capital availability while enforcing the Manifesto's 1.5% daily drawdown cap.
    No hardcoded limits on exposure or slots—only the Council's wisdom and the balance.
    """
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {
            "max_slippage_pct": 10.0,          # High tolerance for low-cap gems
            "min_order_notional_idr": 10000, 
            "max_order_notional_idr": 100000000000, # 100 Billion IDR (Sovereign Cap)
            "max_active_positions": 100,        # High-frequency capacity
            "max_daily_loss_pct": 1.5,          # Manifesto mandated
            "blacklist": ["USDT_IDR"] 
        }
        self.daily_pnl = 0.0
        self.last_reset_date = _today_wib()
        self._load_state()

    def _load_state(self):
        if RISK_STATE_FILE.exists():
            try:
                with open(RISK_STATE_FILE, "r") as f:
                    state = json.load(f)
                    if state.get("last_reset_date") == _today_wib():
                        self.daily_pnl = state.get("daily_pnl", 0.0)
                    else:
                        self.daily_pnl = 0.0
                        self.last_reset_date = _today_wib()
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
        self._check_reset()
        self.daily_pnl += pnl_amount
        self._save_state()
        logger.info(f"💰 Sovereign PnL Tracking: {self.daily_pnl:.2f} IDR")

    def _check_reset(self):
        today = _today_wib()
        if self.last_reset_date != today:
            logger.info("♻️ New day detected. Resetting sovereign PnL.")
            self.daily_pnl = 0.0
            self.last_reset_date = today
            self._save_state()

    def validate_signal(self, signal: Dict, balance_idr: float, active_positions_count: int) -> Tuple[bool, str]:
        """
        Validates a trade signal against sovereign risk parameters.
        V3.5: Strategy is to be situational. Limits are advisory, except for the 1.5% Hard Cap.
        """
        self._check_reset()
        
        # Hard Manifesto Cap
        max_loss = balance_idr * (self.config["max_daily_loss_pct"] / 100)
        if self.daily_pnl < -max_loss:
            return False, f"MANIFESTO CAP: Daily loss reached ({self.daily_pnl:.2f} < -{max_loss:.2f})"

        symbol = signal.get("symbol", "UNKNOWN").upper()
        price = float(signal.get("price", 0))
        side = signal.get("side", "BUY").upper()
        
        if symbol == "UNKNOWN" or price <= 0:
            return False, "Invalid signal data"

        if symbol in self.config["blacklist"]:
            return False, f"Symbol {symbol} is blacklisted"

        # Position slots
        if side == "BUY" and active_positions_count >= self.config["max_active_positions"]:
            return False, f"All {self.config['max_active_positions']} slots occupied."

        # Notional checks
        budget = float(signal.get("budget_idr", self.config["min_order_notional_idr"]))
        if budget < self.config["min_order_notional_idr"]:
            return False, f"Order below minimum notional (Rp{budget})"
        
        if budget > self.config["max_order_notional_idr"]:
            return False, f"Order above extreme sovereign cap (Rp{budget})"

        # Balance check
        if side == "BUY" and balance_idr < budget:
            return False, f"Insufficient balance for sovereign greed (Need Rp{budget}, have Rp{balance_idr})"

        fee_roundtrip_pct = float(signal.get("fee_roundtrip_pct", 1.02)) / 100.0
        effective_budget = budget * (1 - fee_roundtrip_pct)
        if price > 0 and price > effective_budget:
            return False, f"COIN_PRICE_EXCEEDS_BUDGET: 1 coin = Rp{price:,.0f} > fee-adjusted budget Rp{effective_budget:,.0f}"
        if price > 0:
            coin_amount = effective_budget / price
            if coin_amount < 1e-6:
                return False, f"DUST_PREVENTION: Amount {coin_amount:.8f} too small"

        # Slippage/Spread - Sovereignly loose for alpha capture
        meta = signal.get("meta", {})
        spread = float(meta.get("spread_pct", 0))
        if spread > self.config["max_slippage_pct"]:
             return False, f"Spread exceeds 10% sovereign tolerance ({spread}%)"

        return True, "SOVEREIGN_PASS"

    def calculate_amount(self, symbol: str, price: float, budget_idr: float) -> float:
        return round(budget_idr / price, 8)
