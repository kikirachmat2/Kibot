import logging
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from Core.Support.ki_config import WIB, KiConfig

logger = logging.getLogger("RiskGate")

# ─────────────────────────────────────────────
# Capital State Machine thresholds (§16.1)
# ─────────────────────────────────────────────
CAPITAL_MICRO_MAX  =     150_000   # IDR
CAPITAL_SMALL_MAX  =   1_000_000
CAPITAL_NORMAL_MAX =  50_000_000

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
            "max_daily_loss_pct": KiConfig.MAX_DAILY_LOSS_PERCENT,          # Manifesto mandated
            "blacklist": ["USDT_IDR"] 
        }
        # Hard lock: Enforce the 1.5% maximum daily loss limit under all conditions to prevent overrides
        self.config["max_daily_loss_pct"] = KiConfig.MAX_DAILY_LOSS_PERCENT
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
        total_equity_idr = float(
            signal.get("total_equity_idr")
            or signal.get("combined_equity_idr")
            or signal.get("equity_idr")
            or balance_idr
            or 0.0
        )
        if side == "BUY" and price >= total_equity_idr:
            return False, (
                "UNIT_PRICE_ABOVE_TOTAL_BALANCE: "
                f"1 coin = Rp{price:,.0f} must be strictly below total balance/equity "
                f"Rp{total_equity_idr:,.0f}"
            )
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

    # ──────────────────────────────────────────
    # §16.1 — Capital State Machine
    # ──────────────────────────────────────────

    def get_capital_state(
        self,
        balance_idr: float,
        active_slots: int = 0,
        pending_idr: float = 0.0,
    ) -> Dict:
        """
        Determine capital state and derive sizing_mode.

        Returns:
          {
            "capital_state": "MICRO|SMALL|NORMAL|LARGE",
            "cash_idr": float,
            "equity_idr": float,
            "active_slots": int,
            "max_allowed_slots": int,
            "sizing_mode": "ONE_SHOT|PROBE|NORMAL|REDUCED|PROTECT"
          }
        """
        net_cash = max(0.0, balance_idr - pending_idr)

        if net_cash < CAPITAL_MICRO_MAX:
            state      = "MICRO"
            max_slots  = 1
            sizing     = "ONE_SHOT"
        elif net_cash < CAPITAL_SMALL_MAX:
            state      = "SMALL"
            max_slots  = 3
            sizing     = "PROBE"
        elif net_cash < CAPITAL_NORMAL_MAX:
            state      = "NORMAL"
            max_slots  = 10
            sizing     = "NORMAL"
        else:
            state      = "LARGE"
            max_slots  = self.config["max_active_positions"]
            sizing     = "NORMAL"

        # Override sizing_mode when slots almost full
        if active_slots >= max_slots:
            sizing = "PROTECT"
        elif active_slots >= max_slots * 0.8:
            sizing = "REDUCED"

        logger.debug(
            f"[CapitalState] {state} | cash={net_cash:,.0f} IDR | "
            f"slots={active_slots}/{max_slots} | sizing={sizing}"
        )
        return {
            "capital_state":    state,
            "cash_idr":         round(net_cash, 2),
            "equity_idr":       round(balance_idr, 2),
            "active_slots":     active_slots,
            "max_allowed_slots": max_slots,
            "sizing_mode":      sizing,
        }

    def size_from_capital_state(
        self,
        capital_state: Dict,
        daily_context: Optional[Dict] = None,
    ) -> float:
        """
        Derive fractional allocation from capital state + daily context.
        Returns fraction of available cash to deploy per position (0.0–1.0).

        §4 — Entry Sizing Rules:
          MICRO    → use most of cash (one-shot)
          SMALL    → 30-50% per position
          NORMAL   → 10-25% per position
          LARGE    → 5-15% per position
        Daily color modifies: GREEN = reduce, RECOVERY = reduce, FLAT = normal
        """
        base = {
            "MICRO":  0.90,
            "SMALL":  0.40,
            "NORMAL": 0.20,
            "LARGE":  0.10,
        }.get(capital_state.get("capital_state", "NORMAL"), 0.20)

        if daily_context:
            color   = daily_context.get("daily_color", "FLAT")
            urgency = daily_context.get("urgency_level", "LOW")
            quality = daily_context.get("required_trade_quality", "NORMAL")

            # §4: GREEN near midnight → protect sizing
            if color == "GREEN" and urgency in ("HIGH", "CRITICAL"):
                base *= 0.50
            elif color == "GREEN":
                base *= 0.70
            elif color == "RECOVERY":
                base *= 0.60

            # Exceptional quality unlock slightly larger sizing
            if quality == "EXCEPTIONAL":
                base = min(base * 1.15, 0.95)

        return round(min(max(base, 0.05), 0.95), 3)
