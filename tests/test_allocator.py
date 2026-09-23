"""
Unit tests for fixed-ratio buy allocation.
"""

from core.allocator import allocate


def test_allocate_standard():
    alloc = allocate(1_000_000.0)
    assert alloc["BTC"] == 700_000.0
    assert alloc["ETH"] == 300_000.0


def test_allocate_zero_or_negative():
    assert allocate(0.0) == {"BTC": 0.0, "ETH": 0.0}
    assert allocate(-500.0) == {"BTC": 0.0, "ETH": 0.0}


def test_allocate_odd_amount():
    alloc = allocate(333_333.33)
    assert alloc["BTC"] == 233_333.33
    assert alloc["ETH"] == 100_000.0
