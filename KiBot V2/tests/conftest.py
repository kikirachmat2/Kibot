"""Pytest configuration and shared fixtures for KiBot V2."""
import os
import sys
import asyncio
import functools
from pathlib import Path

# Add KiBot V2 root and tests to sys.path
V2_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
if str(V2_ROOT) not in sys.path:
    sys.path.insert(0, str(V2_ROOT))
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import pytest
import tempfile
import shutil

def run_async(coro_func):
    """Decorator to run async test functions cleanly without requiring pytest-asyncio."""
    @functools.wraps(coro_func)
    def wrapper(*args, **kwargs):
        return asyncio.run(coro_func(*args, **kwargs))
    return wrapper

@pytest.fixture
def temp_data_dir():
    """Provides a temporary directory for tests that read/write state files."""
    tmp = tempfile.mkdtemp(prefix="kibot_v2_test_")
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)
