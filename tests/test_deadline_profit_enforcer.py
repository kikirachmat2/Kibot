import json

from Core.Decision.deadline_profit_enforcer import DeadlineProfitEnforcer


def test_deadline_enforcer_state_exists():
    state = DeadlineProfitEnforcer().evaluate_enforcer(0.0, 0.0, 120)
    assert "locked_for_day" in state


def test_deadline_enforcer_global_loss_cutoff(tmp_path):
    # Include start_total_equity_idr so dynamic loss cap = equity * MAX_DAILY_LOSS_PERCENT/100
    # With equity=100_000 and default MAX_DAILY_LOSS_PERCENT=3.0%, cap = 3_000
    # PnL of -6_000 < -3_000 → FATAL_BLOCKED
    (tmp_path / "capital_governor.json").write_text(
        json.dumps({"max_daily_loss_idr": 5_000.0, "start_total_equity_idr": 100_000.0}),
        encoding="utf-8",
    )
    state = DeadlineProfitEnforcer(state_dir=tmp_path).evaluate_enforcer(-35.0, -6_000.0, 120)
    assert state["stage"] == "FATAL_BLOCKED"
    assert state["locked_for_day"] is True
    assert state["required_action"] == "EXIT_ONLY"
    assert "LOSS_CUTOFF" in state["reason"]
