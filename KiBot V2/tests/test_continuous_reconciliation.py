"""
Unit tests for Continuous Truth Reconciliation (VenueLedger) in KiBot V2.
Verifies drift detection against venue truth, HALT_NEW_TRADES enforcement,
and CRITICAL Telegram notification dispatch without silent auto-fixing.
"""
from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from async_helper import run_async

from storage.venue_ledger import VenueLedger
from executor.virtual_ledger import VirtualLedger
from executor.order_router import OrderRouter
from risk.risk_gate import RiskGate
from notifications import telegram_notifier


@run_async
async def test_reconciliation_pass_no_drift():
    """Verify that matching internal and venue states pass reconciliation without halting."""
    vl = VirtualLedger(initial_cash_idr=10_000_000.0)
    vl.cash_idr = 10_000_000.0
    
    venue = VenueLedger(drift_tolerance_idr=1_000.0)
    # Mock venue truth to match internal exactly
    venue.truth_fetcher_hook = AsyncMock(return_value={
        "cash_idr": 10_000_000.0,
        "positions": {},
        "source": "MOCK_EXCHANGE_TRUTH",
    })

    res = await venue.reconcile_once(vl)

    assert res["status"] == "PASS"
    assert res["cash_drift_idr"] == 0.0
    assert not venue.is_halted
    assert len(res["discrepancies"]) == 0


@run_async
async def test_reconciliation_artificial_cash_drift_halts_and_alerts():
    """
    CRITICAL DRIFT TEST:
    Simulates artificial cash drift (internal Rp 10.000.000 vs exchange truth Rp 9.500.000).
    Verifies:
    1. HALT_NEW_TRADES is activated.
    2. Telegram CRITICAL alert is dispatched.
    3. NO silent auto-fix occurs (internal cash remains unchanged).
    """
    vl = VirtualLedger(initial_cash_idr=10_000_000.0)
    vl.cash_idr = 10_000_000.0

    venue = VenueLedger(drift_tolerance_idr=1_000.0)
    # Artificial drift: exchange has 9,500,000 (discrepancy 500,000 IDR)
    venue.truth_fetcher_hook = AsyncMock(return_value={
        "cash_idr": 9_500_000.0,
        "positions": {},
        "source": "MOCK_EXCHANGE_TRUTH",
    })

    with patch.object(telegram_notifier, "send_alert_non_blocking") as mock_alert:
        res = await venue.reconcile_once(vl)

        # 1. Verification of HALT
        assert res["status"] == "FAIL"
        assert venue.is_halted is True
        assert "Venue truth reconciliation drift detected" in venue.halt_reason
        assert res["cash_drift_idr"] == 500_000.0

        # 2. Verification of CRITICAL Alert Dispatch
        assert mock_alert.called
        call_kwargs = mock_alert.call_args[1]
        assert call_kwargs["event_type"] == "RECONCILIATION_DRIFT_HALT"
        assert call_kwargs["severity"] == "CRITICAL"
        assert call_kwargs["force"] is True

        # 3. Verification of NO SILENT AUTO-FIX
        # Internal cash must remain untouched for manual operator audit
        assert vl.cash_idr == 10_000_000.0


@run_async
async def test_reconciliation_position_mismatch_halts():
    """Verify that position mismatch (e.g. ghost position on exchange) halts trading."""
    vl = VirtualLedger(initial_cash_idr=10_000_000.0)
    
    venue = VenueLedger(drift_tolerance_idr=1_000.0)
    # Exchange has a position on ETH/IDR that internal ledger does not know about
    venue.truth_fetcher_hook = AsyncMock(return_value={
        "cash_idr": 10_000_000.0,
        "positions": {"ETH/IDR": 0.5},
        "source": "MOCK_EXCHANGE_TRUTH",
    })

    with patch.object(telegram_notifier, "send_alert_non_blocking") as mock_alert:
        res = await venue.reconcile_once(vl)

        assert res["status"] == "FAIL"
        assert venue.is_halted is True
        assert any(d["type"] == "POSITION_MISMATCH" for d in res["discrepancies"])
        assert mock_alert.called


@run_async
async def test_order_router_blocks_when_reconciliation_halted():
    """Verifies that OrderRouter rejects all new buy orders when VenueLedger is halted."""
    vl = VirtualLedger(initial_cash_idr=10_000_000.0)
    venue = VenueLedger()
    venue.is_halted = True
    venue.halt_reason = "Manual test halt"

    rg = RiskGate()
    router = OrderRouter(
        risk_gate=rg,
        virtual_ledger=vl,
        venue_ledger_instance=venue,
    )

    res = await router.route_buy_order(
        symbol="BTC/IDR",
        price=1_000_000_000.0,
        notional_idr=100_000.0,
    )

    assert res["success"] is False
    assert res["mode"] == "REJECTED_BY_VENUE_LEDGER_HALT"
    assert "BLOCKED: Trading halted by VenueLedger" in res["reason"]
    # Virtual ledger must have no open positions
    assert len(vl.open_positions) == 0


def test_resume_trading_manual_override():
    """Verifies that resume_trading resets the halt state cleanly with operator note."""
    venue = VenueLedger()
    venue.is_halted = True
    venue.halt_reason = "Drift detected"

    venue.resume_trading(operator_note="Discrepancy investigated and approved by operator")

    assert venue.is_halted is False
    assert venue.halt_reason is None
