from __future__ import annotations

from Core.Decision.deterministic_decision_gate import evaluate_live_trade


def test_daily_loss_lock_cannot_be_bypassed() -> None:
    result = evaluate_live_trade(
        {
            "ev_analysis": {"approved": True},
            "pretrade_simulation": {
                "simulation_verdict": "PASS",
                "min_sellable_pass": True,
                "partial_tp_feasible": True,
                "exit_depth_pass": True,
            },
            "expected_net_edge_pct": 2.0,
            "historical_sample_size": 30,
            "spread_pct": 0.4,
            "slippage_est_pct": 0.5,
            "exit_plan_valid": True,
        },
        runtime_state={"risk_state": "LOCKED", "capital_governor": {"daily_loss_breached": True}},
    )
    assert result.approved is False
    assert "RISK_LOCKED" in result.hard_rejects or "DAILY_LOSS_LOCK" in result.hard_rejects

