from __future__ import annotations

import json
from datetime import datetime, timezone

from Core.Support import no_trade_forensics


def test_no_trade_forensics_uses_canonical_risk_when_ai_patrol_lags(tmp_path, monkeypatch) -> None:
    now = datetime.now(timezone.utc).isoformat()
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    payloads = {
        "workflow_automation.json": {
            "current_best_action": "dispatcher may enter eligible candidate",
            "money_truth": {"allow_new_orders": True, "allow_new_orders_reason": "venue-scoped allowances active"},
        },
        "live_truth.json": {
            "updated_at": now,
            "risk_state": "OK",
            "net_pnl_today_idr": 1250.0,
            "total_equity_idr": 153000.0,
            "open_positions": [],
            "dust_positions": [],
            "venue_locks": {"indodax": "RECONCILED"},
        },
        "capital_governor.json": {
            "updated_at": now,
            "status": "BLOCKED_WITH_REASON",
            "allow_new_orders": False,
            "allow_new_orders_reason": "global_daily_loss_cap_breached (-29896.18 <= -2301.68)",
            "daily_pnl_idr": -29896.18,
            "start_total_equity_idr": 153000.0,
            "max_daily_loss_idr": 2301.68,
        },
        "live_order_dispatcher.json": {"status": "ACTIVE", "reason": "dispatcher healthy"},
        "ai_patrol.json": {
            "updated_at": now,
            "support_action": "repair_runtime_blocker",
            "alerts": ["global_daily_loss_cap_breached (-29896.18 <= -2301.68)"],
            "runtime_semantics": {},
        },
        "indodax_top_targets.json": {"top_targets": [{"symbol": "EDEN/IDR", "recommended_action": "ENTER"}]},
        "risk_state.json": {"daily_pnl": 1250.0},
    }

    monkeypatch.setattr(no_trade_forensics, "STATE_DIR", state_dir)
    monkeypatch.setattr(no_trade_forensics, "FORENSICS_FILE", state_dir / "no_trade_forensics.json")

    for name, payload in payloads.items():
        (state_dir / name).write_text(json.dumps(payload), encoding="utf-8")

    result = no_trade_forensics.build_no_trade_forensics()

    assert result["canonical_risk_state"] == "OK"
    assert result["classification"] == "HEALTHY_WAIT"
    assert result["canonical_blockers"] == []
    assert result["ignored_stale_blockers"]
