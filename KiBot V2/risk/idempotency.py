import time
from typing import Dict, Tuple

class IdempotencyGuard:
    """
    Guards against rapid duplicate orders and network retries on the same symbol.
    Ported from KiBot V1 idempotency guard.
    """
    def __init__(self, window_seconds: float = 30.0):
        self.window_seconds = window_seconds
        self._last_order_timestamps: Dict[str, float] = {}

    def can_place_order(self, symbol: str) -> Tuple[bool, str]:
        sym = symbol.upper().strip()
        now = time.time()
        last_ts = self._last_order_timestamps.get(sym)
        if last_ts is not None:
            elapsed = now - last_ts
            if elapsed < self.window_seconds:
                remaining = self.window_seconds - elapsed
                return False, f"Duplicate order blocked by IdempotencyGuard: order placed {elapsed:.1f}s ago ({remaining:.1f}s cool-down remaining)"
        return True, "OK"

    def record_order(self, symbol: str) -> None:
        sym = symbol.upper().strip()
        self._last_order_timestamps[sym] = time.time()

    def clear(self) -> None:
        self._last_order_timestamps.clear()
