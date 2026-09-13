import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

logger = logging.getLogger("KiBotV2.DailyLossCap")

WIB = timezone(timedelta(hours=7))

class DailyLossCap:
    """
    3% Daily Loss Cap ported from KiBot V1.
    - Tracks realized and unrealized PnL against the start-of-day equity anchor.
    - If daily loss exceeds max_daily_loss_pct (default 3.0%), blocks all new buy orders until next day.
    """
    def __init__(self, max_loss_pct: float = 3.0):
        self.max_loss_pct = max_loss_pct
        self.current_date: str = self._today_wib_str()
        self.start_day_equity_idr: float = 0.0
        self.current_daily_pnl_idr: float = 0.0
        self.current_daily_pnl_pct: float = 0.0
        self.is_locked: bool = False
        self.lock_reason: Optional[str] = None

    def _today_wib_str(self) -> str:
        return datetime.now(WIB).strftime("%Y-%m-%d")

    def rollover_if_new_day(self, current_equity_idr: float) -> None:
        today = self._today_wib_str()
        if today != self.current_date:
            logger.info(f"[DailyLossCap] 🌅 New day rollover: {self.current_date} -> {today}. Resetting daily anchor.")
            self.current_date = today
            self.start_day_equity_idr = current_equity_idr
            self.current_daily_pnl_idr = 0.0
            self.current_daily_pnl_pct = 0.0
            self.is_locked = False
            self.lock_reason = None

    def update_pnl(self, current_equity_idr: float, realized_pnl_today: float = 0.0) -> bool:
        self.rollover_if_new_day(current_equity_idr)
        
        if self.start_day_equity_idr <= 0:
            self.start_day_equity_idr = current_equity_idr
            return not self.is_locked

        # Daily loss calculation
        diff_idr = current_equity_idr - self.start_day_equity_idr
        self.current_daily_pnl_idr = diff_idr
        self.current_daily_pnl_pct = (diff_idr / self.start_day_equity_idr) * 100.0

        if not self.is_locked and self.current_daily_pnl_pct <= -self.max_loss_pct:
            self.is_locked = True
            self.lock_reason = (
                f"Daily loss {self.current_daily_pnl_pct:.2f}% breached 3.0% cap "
                f"(Start: Rp {self.start_day_equity_idr:,.0f}, Current: Rp {current_equity_idr:,.0f})"
            )
            logger.warning(f"🛑 [DAILY LOSS CAP LOCKED] {self.lock_reason}")

        return not self.is_locked

    def state_dict(self) -> Dict[str, Any]:
        return {
            "date": self.current_date,
            "max_loss_pct": self.max_loss_pct,
            "start_day_equity_idr": self.start_day_equity_idr,
            "current_daily_pnl_idr": round(self.current_daily_pnl_idr, 2),
            "current_daily_pnl_pct": round(self.current_daily_pnl_pct, 2),
            "is_locked": self.is_locked,
            "lock_reason": self.lock_reason,
        }
