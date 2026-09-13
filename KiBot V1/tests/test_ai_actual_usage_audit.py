from __future__ import annotations

import json
from datetime import datetime, timezone

from tests._script_loader import load_script_module


def test_ai_actual_usage_audit_used(tmp_path, monkeypatch):
    mod = load_script_module("scripts/audit_ai_actual_usage.py", "audit_ai_actual_usage")
    monkeypatch.setattr(mod, "STATE_DIR", tmp_path)
    monkeypatch.setattr(mod, "OUT_FILE", tmp_path / "ai_actual_usage_audit.json")
    now = datetime.now(timezone.utc).isoformat()
    (tmp_path / "ai_decision_trace.json").write_text(json.dumps({"updated_at": now, "objective": "maximize_risk_adjusted_profit_for_boss", "best_action": "WAIT", "reason": "bootstrap"}), encoding="utf-8")
    (tmp_path / "ai_patrol.json").write_text(json.dumps({"updated_at": now, "support_action": "continue"}), encoding="utf-8")
    (tmp_path / "ai_strategy_review.json").write_text(json.dumps({"updated_at": now, "idle_reason_review": "ok"}), encoding="utf-8")
    (tmp_path / "ai_system_inventory.json").write_text(json.dumps({"summary": {"active_components": 26}, "categories": {}, "state_snapshots": {"live_truth.json": {}}}), encoding="utf-8")
    (tmp_path / "workflow_automation.json").write_text(json.dumps({"ai_patrol": {"support_action": "continue"}}), encoding="utf-8")
    (tmp_path / "no_trade_forensics.json").write_text(json.dumps({"movement_reason": "test"}), encoding="utf-8")
    (tmp_path / "strategy_control_actions.json").write_text(json.dumps({"disabled_pairs": []}), encoding="utf-8")

    payload = mod.build_ai_actual_usage_audit()
    assert payload["status"] == "USED"
    assert payload["can_place_order"] is False
    assert payload["can_override_gate"] is False
    assert payload["writes_to_dashboard"] is True
    assert payload["writes_to_forensics"] is True
