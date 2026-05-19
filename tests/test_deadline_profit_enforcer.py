from Core.Decision.deadline_profit_enforcer import DeadlineProfitEnforcer


def test_deadline_enforcer_state_exists():
    state = DeadlineProfitEnforcer().evaluate_enforcer(0.0, 0.0, 120)
    assert "locked_for_day" in state

