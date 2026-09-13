"""
Unit tests for CapitalGovernor in KiBot V2.
Tests enforcement of:
1. Max Concurrent Open Positions Cap.
2. Max Total Capital Exposure Cap (% of Bankroll).
3. Integration as an additional gate in OrderRouter.
"""
import pytest
from async_helper import run_async

from risk.capital_governor import CapitalGovernor
from risk.risk_gate import RiskGate
from executor.virtual_ledger import VirtualLedger
from executor.order_router import OrderRouter


def test_capital_governor_allows_within_limits():
    """Verify that orders within both position count and exposure limits are approved."""
    gov = CapitalGovernor(max_concurrent_positions=3, max_total_exposure_pct=35.0)

    allow, reason = gov.evaluate_order_allocation(
        symbol="BTC/IDR",
        notional_idr=1_000_000.0,
        current_open_positions_count=1,
        current_open_exposure_idr=1_000_000.0,
        total_equity_idr=10_000_000.0,
    )

    assert allow is True
    assert reason == "APPROVED_BY_CAPITAL_GOVERNOR"


def test_capital_governor_rejects_exceeding_concurrent_positions():
    """
    Verify that an order is rejected when current open positions count reaches limit,
    even if capital exposure is low.
    """
    gov = CapitalGovernor(max_concurrent_positions=3, max_total_exposure_pct=50.0)

    # Already 3 positions open
    allow, reason = gov.evaluate_order_allocation(
        symbol="SOL/IDR",
        notional_idr=500_000.0,
        current_open_positions_count=3,
        current_open_exposure_idr=1_500_000.0,
        total_equity_idr=10_000_000.0,
    )

    assert allow is False
    assert "BLOCKED: Max concurrent positions limit (3) reached" in reason
    assert gov.total_rejections == 1


def test_capital_governor_rejects_exceeding_total_exposure():
    """
    Verify that an order is rejected when projected exposure exceeds max_total_exposure_pct,
    even if position count is below the limit.
    """
    gov = CapitalGovernor(max_concurrent_positions=5, max_total_exposure_pct=35.0)

    # 1 position open with Rp 3.000.000 exposure (30%). Adding Rp 1.000.000 makes 40% > 35%.
    allow, reason = gov.evaluate_order_allocation(
        symbol="ETH/IDR",
        notional_idr=1_000_000.0,
        current_open_positions_count=1,
        current_open_exposure_idr=3_000_000.0,
        total_equity_idr=10_000_000.0,
    )

    assert allow is False
    assert "Projected exposure 40.0% exceeds limit 35.0%" in reason
    assert gov.total_rejections == 1


@run_async
async def test_order_router_rejects_when_capital_governor_blocks():
    """
    Integration test with OrderRouter:
    Proves that OrderRouter enforces CapitalGovernor as an additional layer on top of RiskGate.
    Even if RiskGate approves, CapitalGovernor rejection halts order dispatch to VirtualLedger.
    """
    vl = VirtualLedger(initial_cash_idr=10_000_000.0)
    # Simulate 3 already opened positions
    vl.place_paper_buy(symbol="BTC/IDR", price=1_000_000_000.0, notional_idr=1_000_000.0)
    vl.place_paper_buy(symbol="ETH/IDR", price=50_000_000.0, notional_idr=1_000_000.0)
    vl.place_paper_buy(symbol="SOL/IDR", price=2_000_000.0, notional_idr=1_000_000.0)
    assert len(vl.open_positions) == 3

    rg = RiskGate()
    # Limit to 3 positions
    gov = CapitalGovernor(max_concurrent_positions=3, max_total_exposure_pct=50.0)
    router = OrderRouter(risk_gate=rg, virtual_ledger=vl, capital_governor=gov)

    # Attempt to route 4th position
    res = await router.route_buy_order(
        symbol="ADA/IDR",
        price=10_000.0,
        notional_idr=500_000.0,
    )

    assert res["success"] is False
    assert res["mode"] == "REJECTED_BY_CAPITAL_GOVERNOR"
    assert "Max concurrent positions limit (3) reached" in res["reason"]
    # Verify ADA was NOT added to VirtualLedger
    assert "ADA/IDR" not in vl.open_positions
    assert len(vl.open_positions) == 3
