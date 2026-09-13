"""Unit tests for Risk Gates: Circuit Breaker, Daily Loss Cap, and Idempotency Guard."""
import time
import pytest
from risk.circuit_breaker import DrawdownCircuitBreaker
from risk.daily_cap import DailyLossCap
from risk.idempotency import IdempotencyGuard
from risk.risk_gate import RiskGate

def test_circuit_breaker_drawdown_trip():
    """Verify circuit breaker trips when drawdown hits or exceeds 18%."""
    cb = DrawdownCircuitBreaker(threshold_pct=18.0)
    
    # Peak equity: 10,000,000 IDR
    cb.update_equity(10000000.0)
    assert cb.is_tripped is False
    assert cb.current_drawdown_pct == 0.0
    
    # Drops to 8,500,000 IDR (15% DD) -> Not tripped yet
    cb.update_equity(8500000.0)
    assert cb.is_tripped is False
    assert abs(cb.current_drawdown_pct - 15.0) < 0.1
    
    # Drops to 8,100,000 IDR (19% DD) -> TRIPPED
    cb.update_equity(8100000.0)
    assert cb.is_tripped is True
    assert cb.current_drawdown_pct >= 18.0

    # Manual reset requirement
    cb.update_equity(9500000.0)
    # Stays tripped until manual reset
    assert cb.is_tripped is True
    cb.manual_reset("Reset test")
    assert cb.is_tripped is False

def test_daily_loss_cap_trip():
    """Verify daily loss cap trips when intraday losses reach 3%."""
    dlc = DailyLossCap(max_loss_pct=3.0)
    
    # Starting daily equity: 10,000,000 IDR
    dlc.update_pnl(10000000.0)
    assert dlc.is_locked is False
    
    # Loss of 200,000 IDR (2% loss) -> Allowed
    dlc.update_pnl(9800000.0)
    assert dlc.is_locked is False
    assert abs(dlc.current_daily_pnl_pct - (-2.0)) < 0.01
    
    # Additional loss -> Total 9,650,000 IDR (3.5% loss) -> LOCKED
    dlc.update_pnl(9650000.0)
    assert dlc.is_locked is True
    assert dlc.current_daily_pnl_pct <= -3.0

def test_idempotency_duplicate_guard():
    """Verify duplicate order proposals are blocked within the deduplication window."""
    guard = IdempotencyGuard(window_seconds=30.0)
    
    # First submission should be accepted
    can_place, _ = guard.can_place_order("BTC/IDR")
    assert can_place is True
    guard.record_order("BTC/IDR")
    
    # Immediate repeat proposal should be rejected as duplicate
    can_place_repeat, reason = guard.can_place_order("BTC/IDR")
    assert can_place_repeat is False
    assert "Duplicate order blocked" in reason
    
    # Different symbol is not duplicate
    can_place_diff, _ = guard.can_place_order("ETH/IDR")
    assert can_place_diff is True

def test_unified_risk_gate_evaluation():
    """Verify RiskGate integrates all checks and blocks unsafe proposals."""
    gate = RiskGate(
        circuit_breaker=DrawdownCircuitBreaker(threshold_pct=18.0),
        daily_cap=DailyLossCap(max_loss_pct=3.0),
        idempotency=IdempotencyGuard(window_seconds=30.0)
    )
    gate.circuit_breaker.update_equity(10000000.0)
    gate.daily_cap.update_pnl(10000000.0)
    
    # Healthy state -> Approved
    approved, msg = gate.evaluate_new_order("ADA/IDR", notional_idr=250000.0)
    assert approved is True
    assert msg == "APPROVED_BY_RISK_GATE"
    
    # Trip circuit breaker
    gate.circuit_breaker.update_equity(8000000.0)  # 20% DD
    approved_cb, msg_cb = gate.evaluate_new_order("ADA/IDR", notional_idr=250000.0)
    assert approved_cb is False
    assert "Circuit breaker tripped" in msg_cb
