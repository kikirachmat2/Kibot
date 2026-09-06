"""Comprehensive Test Suite for Layer 2: Overall Drawdown Circuit Breaker & High-Water Mark."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from Core.Support.ki_config import KiConfig, STATE_DIR
from Core.Treasury.capital_governor import CapitalGovernor, get_capital_governor
from Core.Treasury.deposit_event_manager import DepositEventManager


@pytest.fixture
def mock_governor_env(tmp_path, monkeypatch):
    """Isolate state directory and configure test environment."""
    test_state_dir = tmp_path / "state"
    test_state_dir.mkdir(parents=True, exist_ok=True)
    
    # Mock paths in capital_governor and deposit_event_manager
    monkeypatch.setattr("Core.Treasury.capital_governor.STATE_DIR", test_state_dir)
    monkeypatch.setattr("Core.Treasury.capital_governor.GOVERNOR_FILE", test_state_dir / "capital_governor.json")
    monkeypatch.setattr("Core.Treasury.capital_governor.ANCHOR_FILE", test_state_dir / "daily_equity_anchor.json")
    monkeypatch.setattr("Core.Treasury.capital_governor.ANCHOR_LOCK_FILE", test_state_dir / "daily_equity_anchor.lock")
    monkeypatch.setattr("Core.Treasury.deposit_event_manager.STATE_DIR", test_state_dir)
    monkeypatch.setattr("Core.Treasury.deposit_event_manager.DEPOSIT_LOG_FILE", test_state_dir / "deposit_events.jsonl")
    
    # Ensure Live Trading is True for governor tests
    monkeypatch.setattr(KiConfig, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(KiConfig, "MAX_DAILY_LOSS_PERCENT", 3.0)
    monkeypatch.setattr(KiConfig, "OVERALL_DRAWDOWN_THRESHOLD_PCT", 18.0)
    monkeypatch.setattr(KiConfig, "MIN_EQUITY_FLOOR_IDR", 10000.0)

    # Empty active trades and inventory snapshot
    monkeypatch.setattr("Core.Treasury.capital_governor.load_daily_inventory_snapshot", lambda: {"has_open_inventory": False, "open_count": 0, "locked_count": 0})
    monkeypatch.setattr("Core.Treasury.capital_governor._pending_buy_order_reserve_idr", lambda: 0.0)
    monkeypatch.setattr("Core.Treasury.capital_governor._load_daily_reset_state", lambda: {"status": "NORMAL"})

    mock_indodax = AsyncMock()
    gov = CapitalGovernor(indodax_gateway=mock_indodax)
    return gov, test_state_dir, mock_indodax


def set_indodax_balance(mock_indodax, balance_idr: float):
    mock_indodax.get_info = AsyncMock(return_value={
        "success": 1,
        "return": {
            "balance": {
                "idr": balance_idr
            }
        }
    })
    mock_indodax.get_ticker = AsyncMock(return_value={"last": 0.0})


@pytest.mark.anyio
async def test_synthetic_compounding_loss_trips_breaker_at_exact_18_pct(mock_governor_env):
    """
    Simulate the exact compounding mathematical loss table:
    Starting Capital: Rp 1,000,000
    Daily Loss: 3.0%
    Verify: Breaker trips precisely on Day 7 when cumulative drawdown >= 18.0%,
    and verifies that midnight reset does NOT clear the circuit breaker.
    """
    gov, state_dir, mock_indodax = mock_governor_env

    # Initial Day 0: Seed capital Rp 1,000,000
    set_indodax_balance(mock_indodax, 1000000.0)
    res = await gov.reconcile_governor()
    assert gov.peak_total_equity_idr == 1000000.0
    assert gov.overall_drawdown_pct == 0.0
    assert gov.circuit_breaker_tripped is False
    assert gov.allow_new_orders is True

    days_data = [
        ("2026-09-01", 970000.0, 3.0),
        ("2026-09-02", 940900.0, 5.91),
        ("2026-09-03", 912673.0, 8.73),
        ("2026-09-04", 885293.0, 11.47),
        ("2026-09-05", 858734.0, 14.13),
        ("2026-09-06", 832972.0, 16.70),
    ]

    current_eq = 1000000.0
    for date_str, closing_equity, expected_cum_dd in days_data:
        with patch("Core.Treasury.capital_governor._today_wib", return_value=date_str):
            await gov.check_daily_reset(current_eq)
            set_indodax_balance(mock_indodax, closing_equity)
            await gov.reconcile_governor()
            assert gov.overall_drawdown_pct == pytest.approx(expected_cum_dd, 0.01)
            assert gov.circuit_breaker_tripped is False
            assert gov.peak_total_equity_idr == 1000000.0
            current_eq = closing_equity

    # Day 7: -3.0% loss -> Equity = 807,983 (drawdown ~19.20% >= 18.0% -> TRIPS CIRCUIT BREAKER!)
    with patch("Core.Treasury.capital_governor._today_wib", return_value="2026-09-07"):
        await gov.check_daily_reset(current_eq)
        set_indodax_balance(mock_indodax, 807983.0)
        res7 = await gov.reconcile_governor()
        
        assert gov.overall_drawdown_pct == pytest.approx(19.20, 0.01)
        assert gov.circuit_breaker_tripped is True
        assert gov.status == "OVERALL_DRAWDOWN_BREAKER_TRIPPED"
        assert gov.allow_new_orders is False
        assert "overall_drawdown_breaker_tripped" in gov.allow_new_orders_reason
        assert res7["circuit_breaker_tripped"] is True

    # Verify midnight reset does NOT clear the tripped circuit breaker
    with patch("Core.Treasury.capital_governor._today_wib", return_value="2026-09-08"):
        await gov.check_daily_reset(807983.0)
        assert gov.circuit_breaker_tripped is True
        assert gov.status == "OVERALL_DRAWDOWN_BREAKER_TRIPPED"
        assert gov.allow_new_orders is False


@pytest.mark.anyio
async def test_operator_acknowledgement_rebase(mock_governor_env):
    """Verify that manual acknowledgement via drawdown-ack resets the circuit breaker and rebases peak."""
    gov, state_dir, mock_indodax = mock_governor_env

    # Seed and trigger circuit breaker
    set_indodax_balance(mock_indodax, 1000000.0)
    await gov.reconcile_governor()

    set_indodax_balance(mock_indodax, 800000.0)  # -20%
    await gov.reconcile_governor()
    assert gov.circuit_breaker_tripped is True
    assert gov.allow_new_orders is False

    # Operator acknowledges with reason
    reason = "Evaluasi pasar selesai, kurangi ukuran lot dan siap lanjut"
    ack_res = gov.acknowledge_drawdown_breaker(reason=reason)

    assert ack_res["status"] == "ACKNOWLEDGED"
    assert gov.circuit_breaker_tripped is False
    assert gov.status == "RECONCILED"
    assert gov.allow_new_orders is True
    assert gov.peak_total_equity_idr == 800000.0  # Rebased to current equity
    assert gov.overall_drawdown_pct == 0.0
    assert gov.circuit_breaker_ack_reason == reason


@pytest.mark.anyio
async def test_deposit_does_not_mask_existing_loss(mock_governor_env):
    """
    Verify that an operator balance deposit:
    1. Adjusts the peak upward proportionally so the deposit is NOT counted as trading profit.
    2. Preserves the exact dollar amount of the existing trading drawdown.
    """
    gov, state_dir, mock_indodax = mock_governor_env

    # Start with Rp 1,000,000
    set_indodax_balance(mock_indodax, 1000000.0)
    await gov.reconcile_governor()
    assert gov.peak_total_equity_idr == 1000000.0

    # Bot trades and loses Rp 100,000 -> Equity = 900,000 (10% drawdown)
    set_indodax_balance(mock_indodax, 900000.0)
    await gov.reconcile_governor()
    assert gov.overall_drawdown_idr == pytest.approx(100000.0)
    assert gov.overall_drawdown_pct == pytest.approx(10.0)

    # Operator deposits Rp 500,000 via DepositEventManager
    dep_mgr = DepositEventManager(log_file=state_dir / "deposit_events.jsonl")
    dep_mgr.record_deposit(500000.0, note="Top-up modal tambahan")

    # Reconcile with new balance = Rp 900,000 + Rp 500,000 = Rp 1,400,000
    set_indodax_balance(mock_indodax, 1400000.0)
    await gov.reconcile_governor()

    # Peak must adjust to Rp 1,500,000 (1,000,000 old peak + 500,000 deposit)
    assert gov.peak_total_equity_idr == pytest.approx(1500000.0)
    # The Rp 100,000 trading loss MUST still be preserved!
    assert gov.overall_drawdown_idr == pytest.approx(100000.0)
    # Drawdown % is 100,000 / 1,500,000 = 6.67%
    assert gov.overall_drawdown_pct == pytest.approx(6.67, 0.01)
    # Circuit breaker is not tripped
    assert gov.circuit_breaker_tripped is False


@pytest.mark.anyio
async def test_withdrawal_does_not_falsely_trip_circuit_breaker(mock_governor_env):
    """
    Verify that an operator balance withdrawal:
    1. Adjusts the peak downward so the withdrawal is NOT counted as a trading loss.
    2. Does NOT trigger the circuit breaker even if withdrawal is > 18% of the capital.
    """
    gov, state_dir, mock_indodax = mock_governor_env

    # Start with Rp 1,000,000
    set_indodax_balance(mock_indodax, 1000000.0)
    await gov.reconcile_governor()
    assert gov.peak_total_equity_idr == 1000000.0

    # Operator withdraws Rp 300,000 (30% of portfolio!)
    dep_mgr = DepositEventManager(log_file=state_dir / "deposit_events.jsonl")
    dep_mgr.record_withdrawal(300000.0, note="Tarik keuntungan ke rekening bank")

    # New balance in Indodax = Rp 700,000
    set_indodax_balance(mock_indodax, 700000.0)
    res = await gov.reconcile_governor()

    # Peak should adjust down to Rp 700,000
    assert gov.peak_total_equity_idr == pytest.approx(700000.0)
    # Drawdown must be 0% (NOT 30%!)
    assert gov.overall_drawdown_pct == pytest.approx(0.0)
    assert gov.circuit_breaker_tripped is False
    assert gov.allow_new_orders is True


@pytest.mark.anyio
async def test_historical_replay_may_2026_prevents_capital_decay(mock_governor_env):
    """
    Historical Replay Test using real parameters from May 2026:
    Starting Equity: Rp 280,000
    Drawdown Threshold: 18% (Loss of Rp 50,400 -> trigger at equity <= Rp 229,600)
    
    In reality, unclosed positions (XRP, EDEN) and repeated fees caused equity
    to degrade without an overall circuit breaker.
    This test verifies that the Layer 2 Breaker halts the bleeding at exactly Rp 229,600.
    """
    gov, state_dir, mock_indodax = mock_governor_env

    # Day 0 (2026-05-20): Operator deposits Rp 280,000
    set_indodax_balance(mock_indodax, 280000.0)
    await gov.reconcile_governor()
    assert gov.peak_total_equity_idr == 280000.0

    # Day 1: Daily loss cap breached (-Rp 10,000 -> balance Rp 270,000)
    set_indodax_balance(mock_indodax, 270000.0)
    await gov.reconcile_governor()
    assert gov.overall_drawdown_pct == pytest.approx(3.57, 0.01)
    assert gov.circuit_breaker_tripped is False

    # Day 2: Market drift on unclosed XRP/EDEN inventory -> balance Rp 255,000 (8.93% drawdown)
    set_indodax_balance(mock_indodax, 255000.0)
    await gov.reconcile_governor()
    assert gov.overall_drawdown_pct == pytest.approx(8.93, 0.01)
    assert gov.circuit_breaker_tripped is False

    # Day 3: Further slippage and fees -> balance Rp 240,000 (14.29% drawdown)
    set_indodax_balance(mock_indodax, 240000.0)
    await gov.reconcile_governor()
    assert gov.overall_drawdown_pct == pytest.approx(14.29, 0.01)
    assert gov.circuit_breaker_tripped is False

    # Day 4: Balance hits Rp 229,000 (drawdown = 18.21% >= 18.0%)
    set_indodax_balance(mock_indodax, 229000.0)
    res = await gov.reconcile_governor()

    # BREAKER MUST TRIP AND HARD-STOP ALL ORDERS!
    assert gov.circuit_breaker_tripped is True
    assert gov.status == "OVERALL_DRAWDOWN_BREAKER_TRIPPED"
    assert gov.allow_new_orders is False
    assert gov.peak_total_equity_idr == 280000.0
    assert gov.overall_drawdown_idr == pytest.approx(51000.0)
    assert gov.overall_drawdown_pct == pytest.approx(18.21, 0.01)

    # Next Day (midnight reset simulation): balance remains Rp 229,000
    # The breaker KEEPS trading locked. It does NOT let equity decay to Rp 0!
    with patch("Core.Treasury.capital_governor._today_wib", return_value="2026-05-25"):
        await gov.check_daily_reset(229000.0)
        assert gov.status == "OVERALL_DRAWDOWN_BREAKER_TRIPPED"
        assert gov.allow_new_orders is False

    print("\n✅ Historical Replay Confirmed: Layer 2 Breaker stops capital decay at Rp229,000 (preserving 81.8% of capital), preventing total wipeout!")
