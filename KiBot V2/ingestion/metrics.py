import time
from typing import Dict, Optional

class DataAgeMetrics:
    """Tracks the freshest timestamp per symbol across all ingestion feeds."""
    def __init__(self):
        self._last_seen_ts: Dict[str, float] = {}

    def record_tick(self, symbol: str, timestamp_s: Optional[float] = None) -> None:
        sym = symbol.upper().strip()
        self._last_seen_ts[sym] = timestamp_s if timestamp_s is not None else time.time()

    def get_data_age_ms(self, symbol: str) -> float:
        sym = symbol.upper().strip()
        last_ts = self._last_seen_ts.get(sym)
        if last_ts is None:
            return float("inf")
        return max(0.0, (time.time() - last_ts) * 1000.0)

    def is_fresh(self, symbol: str, max_age_ms: float = 2500.0) -> bool:
        return self.get_data_age_ms(symbol) <= max_age_ms

    def snapshot(self) -> Dict[str, float]:
        now = time.time()
        return {sym: round((now - ts) * 1000.0, 1) for sym, ts in self._last_seen_ts.items()}

# Global singleton metrics registry
metrics_registry = DataAgeMetrics()
