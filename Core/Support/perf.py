import sys
import asyncio
import time
import psutil

# 1. uvloop helper
def install_uvloop_if_available():
    """Install uvloop event loop policy on non-Windows platforms if available."""
    if sys.platform != "win32":
        try:
            import uvloop
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            return True
        except ImportError:
            pass
    return False

# 2. orjson hotpath parser helper
try:
    import orjson
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
    from cachetools import TTLCache
except ImportError:
    class TTLCache(dict):
        """Standard fallback TTLCache if cachetools is not installed."""
        def __init__(self, maxsize: int, ttl: float):
            super().__init__()
            self.maxsize = maxsize
            self.ttl = ttl
            self._expire_times = {}

        def __setitem__(self, key, value):
            self.expire()
            if len(self) >= self.maxsize and key not in self:
                first_key = next(iter(self.keys()))
                self.pop(first_key, None)
                self._expire_times.pop(first_key, None)
            self._expire_times[key] = time.time() + self.ttl
            super().__setitem__(key, value)

        def __getitem__(self, key):
            self.expire()
            if key not in self:
                raise KeyError(key)
            return super().__getitem__(key)

        def get(self, key, default=None):
            self.expire()
            return super().get(key, default)

        def __contains__(self, key):
            self.expire()
            return super().__contains__(key)

        def expire(self):
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
    cpu_percent = psutil.cpu_percent()
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
        "mem_percent": mem.percent,
        "load_avg": load_avg,
        "budget_ms": budget_ms
    }
