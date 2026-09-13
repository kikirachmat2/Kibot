import json
from Core.Decision.deadline_profit_enforcer import DeadlineProfitEnforcer


def test_deadline_enforcer_state_exists():
    state = DeadlineProfitEnforcer().evaluate_enforcer(0.0, 0.0, 120)
    assert "locked_for_day" in state


def test_deadline_enforcer_2_consecutive_cycles_required(tmp_path):
    (tmp_path / "capital_governor.json").write_text(
        json.dumps({"start_total_equity_idr": 100_000.0}),
        encoding="utf-8",
    )
    enforcer = DeadlineProfitEnforcer(state_dir=tmp_path)

    # Cycle 1: Breach detected for the 1st time → Warning, locked_for_day remains False
    state1 = enforcer.evaluate_enforcer(-35.0, -6_000.0, 120)
    assert state1["locked_for_day"] is False
    assert state1["breach_count"] == 1
    assert "LOSS_CUTOFF_WARNING" in state1["reason"]

    # Cycle 2: Breach confirmed on 2nd cycle → locked_for_day becomes True
    state2 = enforcer.evaluate_enforcer(-35.0, -6_000.0, 120)
    assert state2["locked_for_day"] is True
    assert state2["breach_count"] == 2
    assert state2["stage"] == "FATAL_BLOCKED"
    assert state2["required_action"] == "EXIT_ONLY"
    assert "LOSS_CUTOFF" in state2["reason"]


def test_micro_equity_floor(tmp_path):
    # With micro-equity = 1.45 IDR, effective base equity = 10,000 IDR floor.
    # Loss cap = 3% of 10,000 = 300 IDR.
    # A loss of -1.45 IDR is NOT a breach (-1.45 > -300.0 IDR cap).
    (tmp_path / "capital_governor.json").write_text(
        json.dumps({"start_total_equity_idr": 1.45}),
        encoding="utf-8",
    )
    state = DeadlineProfitEnforcer(state_dir=tmp_path).evaluate_enforcer(-100.0, -1.45, 120)
    assert state["locked_for_day"] is False
    assert state["breach_count"] == 0


def test_real_equity_unaffected_by_floor(tmp_path):
    # With real equity = 500,000 IDR, loss cap = 3% of 500,000 = 15,000 IDR.
    # Floor of 10,000 IDR does NOT affect the calculation.
    # Loss of -10,000 IDR is NOT a breach (-10,000 > -15,000).
    # Loss of -20,000 IDR IS a breach (-20,000 < -15,000).
    (tmp_path / "capital_governor.json").write_text(
        json.dumps({"start_total_equity_idr": 500_000.0}),
        encoding="utf-8",
    )
    enforcer = DeadlineProfitEnforcer(state_dir=tmp_path)
    
    state_ok = enforcer.evaluate_enforcer(-2.0, -10_000.0, 120)
    assert state_ok["locked_for_day"] is False
    assert state_ok["breach_count"] == 0

    state_breach1 = enforcer.evaluate_enforcer(-4.0, -20_000.0, 120)
    assert state_breach1["locked_for_day"] is False
    assert state_breach1["breach_count"] == 1

    state_breach2 = enforcer.evaluate_enforcer(-4.0, -20_000.0, 120)
    assert state_breach2["locked_for_day"] is True
    assert state_breach2["breach_count"] == 2
