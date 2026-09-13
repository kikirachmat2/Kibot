import logging
import time
from typing import Dict, Any, Optional

logger = logging.getLogger("KiBotV2.CircuitBreaker")

class DrawdownCircuitBreaker:
    """
    18% Overall Drawdown Circuit Breaker ported from KiBot V1.
    - Monitors total portfolio equity against historical peak equity.
    - If overall drawdown >= threshold_pct (default 18.0%), trips instantly.
    - Once tripped, all new buy orders are hard-locked until an operator explicitly resets it.
    """
    def __init__(self, threshold_pct: float = 18.0):
        self.threshold_pct = threshold_pct
        self.peak_equity_idr: float = 0.0
        self.current_equity_idr: float = 0.0
        self.current_drawdown_pct: float = 0.0
        self.is_tripped: bool = False
        self.tripped_at: Optional[float] = None
        self.trip_reason: Optional[str] = None

    def update_equity(self, current_equity_idr: float) -> bool:
        """
        Updates current equity and checks if the circuit breaker threshold is breached.
        Returns True if trading is safe (not tripped), False if tripped/locked.
        """
        if current_equity_idr <= 0:
            return not self.is_tripped

        self.current_equity_idr = current_equity_idr
        if self.peak_equity_idr <= 0:
            self.peak_equity_idr = current_equity_idr

        if current_equity_idr > self.peak_equity_idr:
            self.peak_equity_idr = current_equity_idr

        if self.peak_equity_idr > 0:
            drawdown_idr = self.peak_equity_idr - current_equity_idr
            self.current_drawdown_pct = (drawdown_idr / self.peak_equity_idr) * 100.0
        else:
            self.current_drawdown_pct = 0.0

        if not self.is_tripped and self.current_drawdown_pct >= self.threshold_pct:
            self.trip(
                reason=f"Overall drawdown {self.current_drawdown_pct:.2f}% breached maximum threshold {self.threshold_pct:.2f}% "
                       f"(Peak: Rp {self.peak_equity_idr:,.0f}, Current: Rp {self.current_equity_idr:,.0f})"
            )

        return not self.is_tripped

    def trip(self, reason: str) -> None:
        self.is_tripped = True
        self.tripped_at = time.time()
        self.trip_reason = reason
        logger.critical(f"🚨 [CIRCUIT BREAKER TRIPPED] {reason}")

    def manual_reset(self, operator_note: str) -> None:
        logger.warning(f"⚠️ [CIRCUIT BREAKER RESET] Reset by operator. Note: {operator_note}")
        self.is_tripped = False
        self.tripped_at = None
        self.trip_reason = None
        self.peak_equity_idr = self.current_equity_idr
        self.current_drawdown_pct = 0.0

    def state_dict(self) -> Dict[str, Any]:
        return {
            "threshold_pct": self.threshold_pct,
            "peak_equity_idr": self.peak_equity_idr,
            "current_equity_idr": self.current_equity_idr,
            "current_drawdown_pct": round(self.current_drawdown_pct, 2),
            "is_tripped": self.is_tripped,
            "tripped_at": self.tripped_at,
            "trip_reason": self.trip_reason,
        }
