import sys
import asyncio
import time
import psutil
from typing import Any

# 1. uvloop helper
def install_uvloop_if_available():
    """Install uvloop event loop policy on non-Windows platforms if available."""
    if sys.platform != "win32":
        try:
            import uvloop  # type: ignore
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            return True
        except ImportError:
            pass
    return False

# 2. orjson hotpath parser helper
try:
    import orjson  # type: ignore
    def dumps_json(data) -> str:
        """Fast serialize json to string using orjson."""
        return orjson.dumps(data).decode('utf-8')

    def loads_json(data) -> dict:
        """Fast deserialize json from bytes/str using orjson."""
        if isinstance(data, bytes):
            return orjson.loads(data)
        return orjson.loads(data.encode('utf-8'))
except ImportError:
    import json
    def dumps_json(data) -> str:
        """Serialize json using standard json library."""
        return json.dumps(data)

    def loads_json(data) -> dict:
        """Deserialize json using standard json library."""
        return json.loads(data)

# 3. TTL Cache helper
try:
    from cachetools import TTLCache  # type: ignore
except ImportError:
    class TTLCache(dict):
        """Standard fallback TTLCache if cachetools is not installed."""
        def __init__(self, maxsize: int, ttl: float):
            super().__init__()
            self.maxsize = maxsize
            self.ttl = ttl
            self._expire_times = {}

        def __setitem__(self, key, value):
            self._expire_times[key] = time.time() + self.ttl
            if len(self) >= self.maxsize:
                self._purge()
            super().__setitem__(key, value)

        def __getitem__(self, key):
            if key in self._expire_times and time.time() > self._expire_times[key]:
                del self[key]
                del self._expire_times[key]
                raise KeyError(key)
            return super().__getitem__(key)

        def get(self, key, default=None):
            try:
                return self[key]
            except KeyError:
                return default

        def _purge(self):
            now = time.time()
            expired = [k for k, exp in self._expire_times.items() if now > exp]
            for k in expired:
                self.pop(k, None)
                self._expire_times.pop(k, None)

# 4. Bounded gather helper
async def bounded_gather(*aws, limit=4):
    """Run async tasks concurrently up to a set limit."""
    sem = asyncio.Semaphore(limit)
    async def worker(aw):
        async with sem:
            return await aw
    return await asyncio.gather(*(worker(aw) for aw in aws))

# 5. Runtime budget checker
def get_runtime_budget() -> dict:
    """Assess system state (CPU load, memory) to estimate ideal computation budget."""
    raw_cpu = psutil.cpu_percent()
    cpu_percent = float(raw_cpu if isinstance(raw_cpu, (int, float)) else 0.0)
    mem = psutil.virtual_memory()
    load_avg = psutil.getloadavg() if hasattr(psutil, "getloadavg") else (0.0, 0.0, 0.0)
    
    # Estimate allowed compute budget in milliseconds based on OCPU congestion
    if cpu_percent > 88:
        budget_ms = 100.0  # Safe mode, save cycles
    elif cpu_percent > 75:
        budget_ms = 300.0
    elif cpu_percent > 50:
        budget_ms = 600.0
    else:
        budget_ms = 1200.0
        
    return {
        "cpu_percent": cpu_percent,
        "mem_percent": float(getattr(mem, "percent", 0.0) or 0.0),
        "load_avg": load_avg,
        "budget_ms": budget_ms
    }
