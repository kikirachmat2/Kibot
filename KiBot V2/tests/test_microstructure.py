import pytest
from async_helper import run_async

from enrichment.microstructure import IndodaxMicrostructureAnalyzer, microstructure_analyzer
from executor.virtual_ledger import VirtualLedger
from executor.order_router import OrderRouter
from risk.risk_gate import RiskGate


def test_microstructure_vwap_and_slippage_calculation():
    """
    Test that VWAP correctly averages across orderbook depth levels.
    Asks:
    Level 1: 100,000 IDR, 5 coins (500,000 IDR depth)
    Level 2: 102,000 IDR, 10 coins (1,020,000 IDR depth)
    Order size: 1,000,000 IDR.
    Should fill:
    - 500,000 IDR @ 100,000 = 5.0 coins
    - 500,000 IDR @ 102,000 = 4.90196 coins
    Total coins = 9.90196
    Avg price = 1,000,000 / 9.90196 = ~100,990.1 IDR
    Slippage against best ask (100,000) = ~0.99%
    """
    orderbook = {
        "bids": [["99000", "10"], ["98000", "20"]],
        "asks": [["100000", "5"], ["102000", "10"], ["105000", "20"]],
    }
    analyzer = IndodaxMicrostructureAnalyzer(max_allowed_slippage_pct=2.0, max_allowed_spread_pct=2.0)
    res = analyzer.analyze_orderbook(orderbook, target_notional_idr=1_000_000.0, side="BUY")

    assert res.is_depth_sufficient is True
    assert res.best_ask == 100_000.0
    assert res.best_bid == 99_000.0
    assert abs(res.avg_fill_price - 100_990.1) < 1.0
    assert abs(res.slippage_pct - 0.99) < 0.05
    assert res.pass_liquidity is True


def test_microstructure_rejects_when_depth_insufficient():
    """
    WHAT IF scenario (GAP-01 Pre-Trade Check):
    Target size is 5,000,000 IDR, but total ask depth is only 1,520,000 IDR.
    Orderbook must fail depth sufficiency and reject before trade dispatch.
    """
    orderbook = {
        "bids": [["99000", "10"]],
        "asks": [["100000", "5"], ["102000", "10"]],  # Total = 500k + 1020k = 1,520,000 IDR
    }
    analyzer = IndodaxMicrostructureAnalyzer()
    res = analyzer.analyze_orderbook(orderbook, target_notional_idr=5_000_000.0, side="BUY")

    assert res.is_depth_sufficient is False
    assert res.pass_liquidity is False
    assert "INSUFFICIENT_DEPTH" in res.reason
    assert "Target Rp 5,000,000 > Available Rp 1,520,000" in res.reason


def test_virtual_ledger_enforces_depth_check_and_applies_vwap():
    """
    Verify VirtualLedger uses actual orderbook VWAP when available,
    and rejects trade when depth is insufficient (preventing partial fill traps).
    """
    vl = VirtualLedger(initial_cash_idr=10_000_000.0)

    # 1. Order with insufficient depth
    thin_book = {
        "bids": [["1000", "100"]],
        "asks": [["1050", "100"]],  # 105,000 IDR total depth
    }
    res_fail = vl.place_paper_buy(
        symbol="THIN/IDR",
        price=1050.0,
        notional_idr=500_000.0,  # Needs 500k, book only has 105k
        orderbook=thin_book,
    )
    assert res_fail["success"] is False
    assert res_fail["mode"] == "INSUFFICIENT_DEPTH"
    assert "THIN/IDR" not in vl.open_positions
    assert vl.cash_idr == 10_000_000.0  # Cash untouched

    # 2. Order with deep liquidity fills at real VWAP
    deep_book = {
        "bids": [["995", "10000"]],
        "asks": [["1000", "200"], ["1005", "500"]],  # 200k @ 1000 + 502.5k @ 1005 = 702.5k depth
    }
    res_ok = vl.place_paper_buy(
        symbol="DEEP/IDR",
        price=1000.0,
        notional_idr=500_000.0,
        orderbook=deep_book,
    )
    assert res_ok["success"] is True
    pos = vl.open_positions["DEEP/IDR"]
    # Filled across 200k @ 1000 + 300k @ 1005 -> VWAP should be > 1000.0 and < 1005.0
    assert pos.entry_price > 1000.0
    assert pos.entry_price < 1005.0
