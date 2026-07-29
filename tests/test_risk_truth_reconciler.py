from __future__ import annotations

from datetime import datetime, timezone

from Core.Support.risk_truth_reconciler import reconcile_risk_truth


def test_reconciler_ignores_stale_ai_loss_cap_when_live_truth_positive() -> None:
    now = datetime.now(timezone.utc).isoformat()
    live_truth = {
        "updated_at": now,
        "risk_state": "OK",
        "net_pnl_today_idr": 1250.0,
        "total_equity_idr": 153000.0,
    }
    capital_governor = {
        "updated_at": now,
        "status": "BLOCKED_WITH_REASON",
        "allow_new_orders": False,
        "allow_new_orders_reason": "global_daily_loss_cap_breached (-29896.18 <= -2301.68)",
        "daily_pnl_idr": -29896.18,
        "start_total_equity_idr": 153000.0,
        "max_daily_loss_idr": 2301.68,
    }
    risk_state = {"daily_pnl": 1250.0}
    ai_patrol = {
        "updated_at": "2026-06-01T06:45:00+00:00",
        "alerts": ["global_daily_loss_cap_breached (-29896.18 <= -2301.68)"],
        "runtime_semantics": {},
    }
    workflow = {"overall_status": "TRADING_FLOW_READY", "current_best_action": "dispatcher may enter eligible candidate"}

    canonical = reconcile_risk_truth(live_truth, capital_governor, risk_state, ai_patrol, workflow)

    assert canonical["canonical_risk_state"] == "OK"
    assert canonical["allow_new_orders"] is True
    assert canonical["canonical_blockers"] == []
    assert canonical["ignored_stale_blockers"]


def test_reconciler_locks_on_real_loss_cap() -> None:
    now = datetime.now(timezone.utc).isoformat()
    live_truth = {
        "updated_at": now,
        "risk_state": "OK",
        "net_pnl_today_idr": -5000.0,
        "total_equity_idr": 147500.0,
    }
    capital_governor = {
        "updated_at": now,
        "status": "BLOCKED_WITH_REASON",
        "allow_new_orders": False,
        "allow_new_orders_reason": "global_daily_loss_cap_breached (-5000.00 <= -4575.00)",
        "daily_pnl_idr": -5000.0,
        "start_total_equity_idr": 152500.0,
        "max_daily_loss_idr": 4575.0,
    }
    canonical = reconcile_risk_truth(live_truth, capital_governor, {}, {}, {})

    assert canonical["canonical_risk_state"] == "LOCKED"
    assert canonical["allow_new_orders"] is False
    assert canonical["canonical_blockers"]
