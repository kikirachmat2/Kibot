from __future__ import annotations

from Core.Support.churn_guard import evaluate_churn_guard


def test_churn_guard_reduces_frequency_on_flat_churn() -> None:
    result = evaluate_churn_guard(
        {
            "net_growth_audit": {"status": "FLAT_CHURN", "profit_factor": 0.56},
            "capital_governor": {"daily_loss_breached": True},
        }
    )
    assert result["active"] is True
    assert result["max_new_round_trips_next_day"] == 3
    assert result["max_micro_probes_next_day"] == 1
