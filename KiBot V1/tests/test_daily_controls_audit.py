from __future__ import annotations

from Core.Support.growth_audit import audit_daily_controls


def test_daily_controls_reports_recommendation() -> None:
    result = audit_daily_controls({"capital_governor": {"max_daily_loss_idr": 4200.0, "daily_pnl_idr": -100.0}, "workflow": {}})
    assert result["recommendation"] in {"KEEP", "TIGHTEN"}

