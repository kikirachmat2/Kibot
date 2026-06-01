from __future__ import annotations

import json

from tests._script_loader import load_script_module


def test_autonomous_runtime_readiness_ready(tmp_path, monkeypatch):
    mod = load_script_module("scripts/audit_autonomous_runtime_readiness.py", "audit_autonomous_runtime_readiness")
    monkeypatch.setattr(mod, "STATE_DIR", tmp_path)
    monkeypatch.setattr(mod, "OUT_FILE", tmp_path / "autonomous_runtime_readiness_audit.json")
    monkeypatch.setattr(mod, "_service_active", lambda name: True)
    (tmp_path / "live_truth.json").write_text(json.dumps({"updated_at": "2026-06-02T00:00:00Z", "risk_state": "OK"}), encoding="utf-8")
    (tmp_path / "no_trade_forensics.json").write_text(json.dumps({"classification": "HEALTHY_WAIT"}), encoding="utf-8")
    (tmp_path / "workflow_automation.json").write_text(json.dumps({"recovery_mode": {"active": True}}), encoding="utf-8")
    (tmp_path / "target_board_runtime.json").write_text(json.dumps({"updated_at": "2026-06-02T00:00:00Z"}), encoding="utf-8")
    (tmp_path / "recovery_reset_plan.json").write_text(json.dumps({"policy": {"enabled": True}}), encoding="utf-8")
    (tmp_path / "ai_system_inventory.json").write_text(json.dumps({"summary": {"active_components": 26}}), encoding="utf-8")
    (tmp_path / "server_telemetry.json").write_text(json.dumps({"updated_at": "2026-06-02T00:00:00Z"}), encoding="utf-8")
    (tmp_path / "capital_governor.json").write_text(json.dumps({"allow_new_orders_reason": "ok"}), encoding="utf-8")

    payload = mod.build_autonomous_runtime_readiness_audit()
    assert payload["status"] == "READY"
    assert payload["service_ok"] is True
    assert payload["ai_ready"] is True
    assert payload["target_board_fresh"] is True

