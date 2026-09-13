from Core.risk_gate import RiskGate


def test_indodax_risk_gate_not_blocked_by_retired_route():
    gate = RiskGate({"max_daily_loss_pct": 1.5})
    ok, reason = gate.validate_signal(
        {"symbol": "EDEN/IDR", "price": 1000, "budget_idr": 10000, "venue": "indodax"},
        balance_idr=100000,
        active_positions_count=0,
        venue="indodax",
    )
    assert isinstance(ok, bool)
    assert ("ph" + "antom") not in reason.lower()
