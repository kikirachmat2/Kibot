"""Unit tests for Slippage-Aware Orderbook Spread Sizing Guard in AutonomousSizing."""

import pytest
from Core.Trading.autonomous_sizing import AutonomousSizing


def test_sizing_normal_when_spread_low():
    sizing = AutonomousSizing()
    res = sizing.size(
        total_capital_idr=1000000.0,
        venue_capital_idr=1000000.0,
        route_bucket_idr=500000.0,
        available_balance_idr=500000.0,
        daily_risk_remaining_idr=30000.0,
        liquidity_usd=50000.0,
        slippage_pct=0.2,
        confidence=0.85,
        ev_pct=1.5,
        spread_pct=0.5,  # low spread
    )
    assert res["approved"] is True
    assert res["size_idr"] > 0
    assert "spread_too_wide_slippage_risk" not in res["reason"]


def test_sizing_discounted_when_spread_elevated():
    sizing = AutonomousSizing()

    res_normal = sizing.size(
        total_capital_idr=1000000.0,
        venue_capital_idr=1000000.0,
        route_bucket_idr=500000.0,
        available_balance_idr=500000.0,
        daily_risk_remaining_idr=30000.0,
        liquidity_usd=50000.0,
        slippage_pct=0.2,
        confidence=0.85,
        ev_pct=1.5,
        spread_pct=0.5,
    )

    res_elevated = sizing.size(
        total_capital_idr=1000000.0,
        venue_capital_idr=1000000.0,
        route_bucket_idr=500000.0,
        available_balance_idr=500000.0,
        daily_risk_remaining_idr=30000.0,
        liquidity_usd=50000.0,
        slippage_pct=0.2,
        confidence=0.85,
        ev_pct=1.5,
        spread_pct=1.8,  # elevated spread (1.8%)
    )

    assert res_elevated["approved"] is True
    assert res_elevated["size_idr"] < res_normal["size_idr"]
    assert "spread_elevated" in res_elevated["guard_reasons"]


def test_sizing_blocked_when_spread_too_wide():
    sizing = AutonomousSizing()
    res = sizing.size(
        total_capital_idr=1000000.0,
        venue_capital_idr=1000000.0,
        route_bucket_idr=500000.0,
        available_balance_idr=500000.0,
        daily_risk_remaining_idr=30000.0,
        liquidity_usd=50000.0,
        slippage_pct=0.2,
        confidence=0.85,
        ev_pct=1.5,
        spread_pct=2.8,  # too wide (>2.5%)
    )
    assert res["approved"] is False
    assert res["size_idr"] == 0
    assert "spread_too_wide_slippage_risk" in res["reason"]
