from __future__ import annotations

import json

from tests._script_loader import load_script_module


def test_server_extensions_usage_used(tmp_path, monkeypatch):
    mod = load_script_module("scripts/audit_server_extensions_usage.py", "audit_server_extensions_usage")
    monkeypatch.setattr(mod, "STATE_DIR", tmp_path)
    monkeypatch.setattr(mod, "OUT_FILE", tmp_path / "server_extensions_usage_audit.json")
    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/bin/{name}" if name in {"gh", "copilot", "crush"} else None)
    monkeypatch.setattr(mod, "_service_active", lambda name: True)
    (tmp_path / "server_telemetry.json").write_text(json.dumps({"updated_at": "2026-06-02T00:00:00Z"}), encoding="utf-8")
    (tmp_path / "ai_system_inventory.json").write_text(json.dumps({"state_snapshots": {"live_truth.json": {}}}), encoding="utf-8")

    payload = mod.build_server_extensions_usage_audit()
    assert payload["status"] == "USED"
    assert payload["tools"]["gh"] is True
    assert payload["tools"]["ollama"] is True
    assert payload["extension_usage"]["telemetry_writes"] is True

