from __future__ import annotations

from Core.Support.recovery_mode_policy import build_recovery_mode_policy


def test_recovery_mode_policy_activates_on_flat_churn() -> None:
    result = build_recovery_mode_policy(
        {
            "net_growth_audit": {"status": "FLAT_CHURN", "profit_factor": 0.56},
            "capital_governor": {"daily_loss_breached": True},
            "fill_quality_audit": {"status": "INCOMPLETE_ACCOUNTING"},
            "round_trip_accounting": {"stats": {"closed_round_trips": 4}},
        }
    )
    assert result["active"] is True
    assert result["closed_round_trip_accounting_ok"] is True
