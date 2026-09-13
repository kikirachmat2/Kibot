import time
from typing import Tuple, Dict, Any, Optional

from .circuit_breaker import DrawdownCircuitBreaker
from .daily_cap import DailyLossCap
from .idempotency import IdempotencyGuard
from config import settings

class RiskGate:
    """
    Unified ultra-fast risk gate (< 1ms).
    Evaluates:
    1. 18% Drawdown Circuit Breaker
    2. 3% Daily Loss Cap
    3. Idempotency Guard (anti-double buy)
    """
    def __init__(
        self,
        circuit_breaker: Optional[DrawdownCircuitBreaker] = None,
        daily_cap: Optional[DailyLossCap] = None,
        idempotency: Optional[IdempotencyGuard] = None,
    ):
        self.circuit_breaker = circuit_breaker or DrawdownCircuitBreaker(threshold_pct=settings.MAX_DRAWDOWN_PCT)
        self.daily_cap = daily_cap or DailyLossCap(max_loss_pct=settings.MAX_DAILY_LOSS_PCT)
        self.idempotency = idempotency or IdempotencyGuard(window_seconds=settings.IDEMPOTENCY_WINDOW_SECONDS)

    def evaluate_new_order(self, symbol: str, notional_idr: float) -> Tuple[bool, str]:
        # 1. Circuit Breaker Check
        if self.circuit_breaker.is_tripped:
            return False, f"BLOCKED: Circuit breaker tripped ({self.circuit_breaker.trip_reason})"

        # 2. Daily Loss Cap Check
        if self.daily_cap.is_locked:
            return False, f"BLOCKED: Daily loss cap locked ({self.daily_cap.lock_reason})"

        # 3. Idempotency Check
        can_place, idem_reason = self.idempotency.can_place_order(symbol)
        if not can_place:
            return False, f"BLOCKED: {idem_reason}"

        # 4. Minimum notional check
        if notional_idr < settings.MIN_ORDER_NOTIONAL_IDR:
            return False, f"BLOCKED: Order size Rp {notional_idr:,.0f} below minimum Rp {settings.MIN_ORDER_NOTIONAL_IDR:,.0f}"

        return True, "APPROVED_BY_RISK_GATE"

    def record_order_placed(self, symbol: str) -> None:
        self.idempotency.record_order(symbol)

    def state_dict(self) -> Dict[str, Any]:
        return {
            "circuit_breaker": self.circuit_breaker.state_dict(),
            "daily_cap": self.daily_cap.state_dict(),
        }
