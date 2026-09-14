import time
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

logger = logging.getLogger("KiBotV2.ChurnGuard")

class ChurnGuard:
    """
    Guards against portfolio fee bleeding and flat churn:
    1. Rolling Profit Factor Gate: If rolling PF of last 10 trades < 0.80,
       restricts new entries to max 3 trades per calendar day.
    2. Fee Bleeding Cap: If accumulated daily taker fees >= 0.75% of total equity,
       completely halts new entries for the rest of the calendar day.
    """
    def __init__(
        self,
        rolling_window_size: int = 10,
        min_rolling_profit_factor: float = 0.80,
        guarded_max_daily_trades: int = 3,
        max_daily_fee_pct: float = 0.75, # 0.75% of equity
    ):
        self.window_size = rolling_window_size
        self.min_pf = min_rolling_profit_factor
        self.guarded_daily_cap = guarded_max_daily_trades
        self.max_daily_fee_pct = max_daily_fee_pct

        self.daily_trades_count: int = 0
        self.daily_fees_idr: float = 0.0
        self.current_day_str: str = self._get_today_str()

    def _get_today_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _check_day_rollover(self) -> None:
        today = self._get_today_str()
        if today != self.current_day_str:
            logger.info(
                f"[ChurnGuard] 🌅 Day rollover detected: {self.current_day_str} -> {today}. "
                f"Resetting daily trades ({self.daily_trades_count}) and fees (Rp {self.daily_fees_idr:,.0f})."
            )
            self.current_day_str = today
            self.daily_trades_count = 0
            self.daily_fees_idr = 0.0

    def record_trade_closed(self, realized_pnl_idr: float, fee_idr: float) -> None:
        """Called upon trade closure to update daily tracking counters."""
        self._check_day_rollover()
        self.daily_trades_count += 1
        self.daily_fees_idr += abs(fee_idr)

    def evaluate_entry_allowed(
        self,
        trade_history: List[Dict[str, Any]],
        current_equity_idr: float,
    ) -> Tuple[bool, str]:
        """
        Evaluates whether portfolio health allows opening a new position.
        Returns:
            (is_allowed: bool, reason: str)
        """
        self._check_day_rollover()

        # 1. Check Fee Bleeding Cap (0.75% of equity)
        if current_equity_idr > 0:
            fee_ratio_pct = (self.daily_fees_idr / current_equity_idr) * 100.0
            if fee_ratio_pct >= self.max_daily_fee_pct:
                reason = (
                    f"FEE_BLEEDING_CAP_REACHED: Daily fees Rp {self.daily_fees_idr:,.2f} "
                    f"({fee_ratio_pct:.2f}%) exceeds limit {self.max_daily_fee_pct:.2f}% of equity. "
                    f"New entries locked until next calendar day."
                )
                logger.warning(f"[ChurnGuard] 🛑 {reason}")
                return False, reason

        # 2. Check Rolling Profit Factor Gate
        if trade_history and len(trade_history) >= self.window_size:
            recent_trades = trade_history[-self.window_size:]
            gross_profit = sum(t.get("realized_pnl_idr", 0.0) for t in recent_trades if t.get("realized_pnl_idr", 0.0) > 0.0)
            gross_loss = abs(sum(t.get("realized_pnl_idr", 0.0) for t in recent_trades if t.get("realized_pnl_idr", 0.0) < 0.0))
            
            if gross_loss > 0.0:
                rolling_pf = gross_profit / gross_loss
            elif gross_profit > 0.0:
                rolling_pf = 99.0
            else:
                rolling_pf = 0.0

            if rolling_pf < self.min_pf:
                if self.daily_trades_count >= self.guarded_daily_cap:
                    reason = (
                        f"ROLLING_CHURN_GUARD: Rolling PF ({rolling_pf:.2f}) < {self.min_pf:.2f} over last "
                        f"{self.window_size} trades. Guarded daily trade cap ({self.guarded_daily_cap}) reached "
                        f"(today: {self.daily_trades_count} trades). New entries locked until next day."
                    )
                    logger.warning(f"[ChurnGuard] 🛑 {reason}")
                    return False, reason

        return True, "CHURN_GUARD_OK"

    def state_dict(self) -> Dict[str, Any]:
        return {
            "daily_trades_count": self.daily_trades_count,
            "daily_fees_idr": self.daily_fees_idr,
            "current_day_str": self.current_day_str,
        }

    def load_state(self, state: Dict[str, Any]) -> None:
        self.daily_trades_count = state.get("daily_trades_count", 0)
        self.daily_fees_idr = state.get("daily_fees_idr", 0.0)
        self.current_day_str = state.get("current_day_str", self._get_today_str())
