import pytest
import time
from unittest.mock import patch

from risk.pair_quarantine import PairQuarantineManager
from risk.churn_guard import ChurnGuard
from risk.capital_governor import CapitalGovernor
from executor.order_router import OrderRouter
from executor.virtual_ledger import VirtualLedger
from risk.risk_gate import RiskGate
from config import settings


def test_consecutive_loss_trigger():
    """Test that 3 consecutive losses on a pair trigger a 24h quarantine."""
    quarantine = PairQuarantineManager(consecutive_loss_threshold=3, consecutive_loss_cooldown_s=86400)
    
    # Loss 1
    res1 = quarantine.record_trade_result("BTCIDR", realized_pnl_idr=-10000.0, exit_reason="STOP_LOSS")
    assert res1 is None
    is_q, _ = quarantine.is_quarantined("BTCIDR")
    assert is_q is False

    # Loss 2
    res2 = quarantine.record_trade_result("BTCIDR", realized_pnl_idr=-5000.0, exit_reason="STOP_LOSS")
    assert res2 is None
    is_q, _ = quarantine.is_quarantined("BTCIDR")
    assert is_q is False

    # Loss 3 -> MUST trigger 24h quarantine
    res3 = quarantine.record_trade_result("BTCIDR", realized_pnl_idr=-8000.0, exit_reason="STOP_LOSS")
    assert res3 == "QUARANTINED_CONSECUTIVE_LOSSES"
    
    is_q, reason = quarantine.is_quarantined("BTCIDR")
    assert is_q is True
    assert "3_CONSECUTIVE_LOSSES" in reason

    # Win on another pair should not affect BTCIDR quarantine
    quarantine.record_trade_result("ETHIDR", realized_pnl_idr=50000.0, exit_reason="TAKE_PROFIT")
    is_q_btc, _ = quarantine.is_quarantined("BTCIDR")
    assert is_q_btc is True
    is_q_eth, _ = quarantine.is_quarantined("ETHIDR")
    assert is_q_eth is False


def test_consecutive_timeout_churn_trigger():
    """Test that 3 consecutive timeouts (MAX_HOLD_TIME_EXPIRED) trigger a 4h quarantine."""
    quarantine = PairQuarantineManager(consecutive_timeout_threshold=3, consecutive_timeout_cooldown_s=14400)

    # Timeout 1 & 2
    quarantine.record_trade_result("BTCIDR", realized_pnl_idr=-2000.0, exit_reason="MAX_HOLD_TIME_EXPIRED")
    quarantine.record_trade_result("BTCIDR", realized_pnl_idr=-1500.0, exit_reason="MAX_HOLD_TIME_EXPIRED")
    assert quarantine.is_quarantined("BTCIDR")[0] is False

    # Timeout 3 -> MUST trigger 4h quarantine
    res = quarantine.record_trade_result("BTCIDR", realized_pnl_idr=-1800.0, exit_reason="MAX_HOLD_TIME_EXPIRED")
    assert res == "QUARANTINED_CONSECUTIVE_TIMEOUTS"

    is_q, reason = quarantine.is_quarantined("BTCIDR")
    assert is_q is True
    assert "3_CONSECUTIVE_TIMEOUTS_CHURN" in reason


def test_quarantine_ttl_expiry():
    """Test that quarantine automatically expires after cooldown duration."""
    quarantine = PairQuarantineManager(consecutive_loss_threshold=2, consecutive_loss_cooldown_s=2)
    quarantine.record_trade_result("SOL/IDR", realized_pnl_idr=-1000.0, exit_reason="STOP_LOSS")
    quarantine.record_trade_result("SOL/IDR", realized_pnl_idr=-1000.0, exit_reason="STOP_LOSS")
    
    assert quarantine.is_quarantined("SOL/IDR")[0] is True
    
    # Fast forward past TTL
    with patch("time.time", return_value=time.time() + 5.0):
        is_q, _ = quarantine.is_quarantined("SOL/IDR")
        assert is_q is False


def test_permanent_blacklist():
    """Test that permanently blacklisted pairs are always blocked."""
    quarantine = PairQuarantineManager()
    for symbol in ["TRXIDR", "trx_idr", "TRX/IDR", "SHIBIDR", "BNBIDR"]:
        is_q, reason = quarantine.is_quarantined(symbol)
        assert is_q is True
        assert reason == "PERMANENT_BLACKLIST"


def test_churn_guard_rolling_profit_factor_gate():
    """Test that rolling PF < 0.80 enforces max 3 trades per day."""
    churn_guard = ChurnGuard(rolling_window_size=10, min_rolling_profit_factor=0.80, guarded_max_daily_trades=3)
    
    # Construct 10 losing trades (PF = 0.0)
    history = [{"realized_pnl_idr": -5000.0} for _ in range(10)]
    
    # 0, 1, 2 trades today -> Allowed
    churn_guard.daily_trades_count = 0
    assert churn_guard.evaluate_entry_allowed(history, current_equity_idr=10_000_000.0)[0] is True
    
    churn_guard.daily_trades_count = 2
    assert churn_guard.evaluate_entry_allowed(history, current_equity_idr=10_000_000.0)[0] is True

    # 3 trades today -> BLOCKED by guarded cap
    churn_guard.daily_trades_count = 3
    is_ok, reason = churn_guard.evaluate_entry_allowed(history, current_equity_idr=10_000_000.0)
    assert is_ok is False
    assert "ROLLING_CHURN_GUARD" in reason


def test_churn_guard_fee_bleeding_cap():
    """Test that daily fees exceeding 0.75% of equity block new entries."""
    churn_guard = ChurnGuard(max_daily_fee_pct=0.75)
    equity = 10_000_000.0
    # 0.75% of 10M = 75,000 IDR
    
    churn_guard.daily_fees_idr = 50_000.0
    assert churn_guard.evaluate_entry_allowed([], equity)[0] is True

    churn_guard.daily_fees_idr = 75_001.0
    is_ok, reason = churn_guard.evaluate_entry_allowed([], equity)
    assert is_ok is False
    assert "FEE_BLEEDING_CAP_REACHED" in reason


def test_capital_governor_phase3_integration():
    """Test full integration of PairQuarantine and ChurnGuard into CapitalGovernor."""
    quarantine = PairQuarantineManager()
    churn_guard = ChurnGuard()
    governor = CapitalGovernor(pair_quarantine=quarantine, churn_guard=churn_guard)

    # 1. Normal state -> Approved
    allow, _ = governor.evaluate_order_allocation(
        symbol="BTCIDR",
        notional_idr=1_000_000.0,
        current_open_positions_count=0,
        current_open_exposure_idr=0.0,
        total_equity_idr=10_000_000.0,
    )
    assert allow is True

    # 2. Quarantine BTCIDR -> Blocked by PairQuarantine
    quarantine.quarantine_pair("BTCIDR", "TEST_ISOLATION", duration_seconds=3600)
    allow_q, reason_q = governor.evaluate_order_allocation(
        symbol="BTCIDR",
        notional_idr=1_000_000.0,
        current_open_positions_count=0,
        current_open_exposure_idr=0.0,
        total_equity_idr=10_000_000.0,
    )
    assert allow_q is False
    assert "quarantined" in reason_q

    # 3. Un-quarantine BTCIDR, but trigger ChurnGuard fee cap -> Blocked by ChurnGuard
    quarantine.lift_quarantine("BTCIDR")
    churn_guard.daily_fees_idr = 80_000.0
    allow_cg, reason_cg = governor.evaluate_order_allocation(
        symbol="BTCIDR",
        notional_idr=1_000_000.0,
        current_open_positions_count=0,
        current_open_exposure_idr=0.0,
        total_equity_idr=10_000_000.0,
    )
    assert allow_cg is False
    assert "FEE_BLEEDING_CAP_REACHED" in reason_cg


def test_what_if_dual_guards_active_defensive_zero_trade():
    """
    CRITICAL 'WHAT IF' SAFETY TEST:
    Both PairQuarantine AND ChurnGuard are active simultaneously, and BTCIDR
    (the only approved candidate) is blocked by both guards.
    Verifies:
    1. No logical collision or exceptions occur.
    2. OrderRouter safely returns REJECTED_BY_CAPITAL_GOVERNOR.
    3. VirtualLedger opens 0 positions.
    4. System cleanly remains in defensive idle 'zero-trade' mode.
    """
    quarantine = PairQuarantineManager()
    churn_guard = ChurnGuard()
    governor = CapitalGovernor(pair_quarantine=quarantine, churn_guard=churn_guard)
    
    ledger = VirtualLedger(initial_cash_idr=10_000_000.0)
    risk_gate = RiskGate()
    router = OrderRouter(risk_gate=risk_gate, virtual_ledger=ledger, capital_governor=governor)

    # Actively quarantine BTCIDR (e.g. after 3 consecutive timeouts)
    quarantine.quarantine_pair("BTCIDR", "3_CONSECUTIVE_TIMEOUTS_CHURN", duration_seconds=14400)
    # AND trigger ChurnGuard fee cap
    churn_guard.daily_fees_idr = 100_000.0

    # Attempt to route order for BTCIDR
    import asyncio
    res = asyncio.run(router.route_buy_order(
        symbol="BTCIDR",
        price=1_350_000_000.0,
        notional_idr=1_000_000.0,
    ))

    # Must be safely rejected without crashing
    assert res["success"] is False
    assert res["mode"] == "REJECTED_BY_CAPITAL_GOVERNOR"
    assert "quarantined" in res["reason"]

    # Virtual ledger remains pristine
    assert len(ledger.open_positions) == 0
    assert ledger.get_total_equity() == 10_000_000.0
