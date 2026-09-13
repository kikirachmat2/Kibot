import time
from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class CacheEntry:
    data: Dict[str, Any]
    expires_at: float

class EnrichmentCache:
    """
    High-speed, zero-wait in-memory cache for external news & sentiment enrichment data.
    Read latency is < 1 microsecond.
    """
    def __init__(self, default_ttl_s: float = 1800.0):
        self.default_ttl_s = default_ttl_s
        self._cache: Dict[str, CacheEntry] = {}

    def get(self, symbol: str) -> Optional[Dict[str, Any]]:
        sym = symbol.upper().strip()
        entry = self._cache.get(sym)
        if not entry:
            return None
        if time.time() > entry.expires_at:
            # Expired
            self._cache.pop(sym, None)
            return None
        return entry.data

    def set(self, symbol: str, data: Dict[str, Any], ttl_s: Optional[float] = None) -> None:
        sym = symbol.upper().strip()
        ttl = ttl_s if ttl_s is not None else self.default_ttl_s
        self._cache[sym] = CacheEntry(
            data=data,
            expires_at=time.time() + ttl,
        )

    def has(self, symbol: str) -> bool:
        return self.get(symbol) is not None

    def clear(self) -> None:
        self._cache.clear()

# Global singleton cache instance
enrichment_cache = EnrichmentCache()
