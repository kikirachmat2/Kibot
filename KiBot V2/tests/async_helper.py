"""Async test execution helper."""
import asyncio
import functools

def run_async(coro_func):
    """Decorator to run async test functions cleanly without requiring pytest-asyncio."""
    @functools.wraps(coro_func)
    def wrapper(*args, **kwargs):
        return asyncio.run(coro_func(*args, **kwargs))
    return wrapper
