from __future__ import annotations

from Core.Decision.live_opportunity_tier import classify_live_opportunity


def test_flat_churn_disables_micro_probe_when_risk_locked() -> None:
    result = classify_live_opportunity(
        {"expected_net_edge_pct": 2.0, "historical_sample_size": 1, "micro_probe_requested": True},
        {"approved": True, "expected_net_edge_pct": 2.0, "sample_size": 1},
        {"simulation_verdict": "PASS", "min_sellable_pass": True, "exit_depth_pass": True, "partial_tp_feasible": True},
        {"daily_loss_breached": True},
        {"status": "OK"},
        {"micro_probe_enabled": True, "micro_probe_remaining_today": 1},
    )
    assert result.approved is False
