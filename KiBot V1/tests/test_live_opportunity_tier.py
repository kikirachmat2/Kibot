from __future__ import annotations

from Core.Decision.live_opportunity_tier import classify_live_opportunity


def test_a_plus_trade_approved() -> None:
    result = classify_live_opportunity(
        {"spread_pct": 0.3, "slippage_est_pct": 0.4, "historical_sample_size": 25, "exit_plan_valid": True, "size_idr": 12000},
        {"approved": True, "expected_net_edge_pct": 1.5},
        {"simulation_verdict": "PASS", "min_sellable_pass": True, "partial_tp_feasible": True, "exit_depth_pass": True},
        {"daily_loss_breached": False},
        {"status": "OK"},
        {"a_plus_min_ev_sample_size": 20, "a_plus_min_net_edge_pct": 1.2, "micro_probe_enabled": True},
    )
    assert result.tier == "A_PLUS"
    assert result.approved is True
    assert result.label == "LIVE_A_PLUS"


def test_micro_probe_allowed_for_small_sample_non_negative_ev() -> None:
    result = classify_live_opportunity(
        {"spread_pct": 0.4, "slippage_est_pct": 0.5, "historical_sample_size": 2, "exit_plan_valid": True, "size_idr": 11000},
        {"approved": False, "expected_net_edge_pct": 0.4},
        {"simulation_verdict": "PASS", "min_sellable_pass": True, "partial_tp_feasible": True, "exit_depth_pass": True},
        {"daily_loss_breached": False},
        {"status": "OK"},
        {"micro_probe_enabled": True, "micro_probe_remaining_today": 1, "micro_probe_max_size_idr": 15000, "micro_probe_min_size_idr": 10000, "micro_probe_max_spread_pct": 0.6, "micro_probe_max_slippage_pct": 0.8, "a_plus_min_ev_sample_size": 20, "a_plus_min_net_edge_pct": 1.2},
    )
    assert result.tier == "MICRO_PROBE"
    assert result.approved is True
    assert result.label == "LIVE_MICRO_PROBE"


def test_negative_ev_rejected_no_micro_probe() -> None:
    result = classify_live_opportunity(
        {"spread_pct": 0.4, "slippage_est_pct": 0.5, "historical_sample_size": 2, "exit_plan_valid": True, "size_idr": 11000},
        {"approved": False, "expected_net_edge_pct": -0.2},
        {"simulation_verdict": "PASS", "min_sellable_pass": True, "partial_tp_feasible": True, "exit_depth_pass": True},
        {"daily_loss_breached": False},
        {"status": "OK"},
        {"micro_probe_enabled": True, "micro_probe_remaining_today": 1, "micro_probe_max_size_idr": 15000, "micro_probe_min_size_idr": 10000, "micro_probe_max_spread_pct": 0.6, "micro_probe_max_slippage_pct": 0.8, "a_plus_min_ev_sample_size": 20, "a_plus_min_net_edge_pct": 1.2},
    )
    assert result.tier == "REJECT"
    assert result.approved is False
    assert result.reason == "EDGE_NOT_POSITIVE"

