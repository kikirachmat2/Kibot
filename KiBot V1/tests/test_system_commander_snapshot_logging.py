from __future__ import annotations

from Core.Support.system_commander import SystemCommander


def test_system_commander_emits_snapshot_event(tmp_path, monkeypatch):
    commander = SystemCommander(str(tmp_path))
    commander.state_dir.mkdir(parents=True, exist_ok=True)
    captured = []

    def fake_log_event(event_type, payload):
        captured.append((event_type, payload))

    monkeypatch.setattr("Core.Intelligence.decision_journal.log_event", fake_log_event)
    monkeypatch.setattr(commander, "_read_json", lambda path, default: {})

    state_dict = {
        "system_state": "HEALTHY",
        "inventory_utilization_score": 0.84,
        "drift": "SYNCED",
        "trading_allowed_by_system": True,
        "operator_required": False,
        "services": {"kibot-master": "active"},
        "providers": {"ollama": {"status": "online"}},
        "sources": {"gh": {"status": "available"}},
    }
    matrix = {
        "tools": [
            {"name": "kibotctl", "status": "available", "active": True, "version": "ok"},
            {"name": "gh", "status": "available", "active": True, "version": "gh"},
            {"name": "aider", "status": "available", "active": True, "version": "aider"},
            {"name": "copilot", "status": "available", "active": True, "version": "copilot"},
        ]
    }
    resources = {"cpu": 12.5, "ram": 34.5, "disk": 56.7}

    commander._emit_snapshot_event(state_dict, matrix, resources)

    assert captured, "system commander snapshot was not mirrored"
    event_type, snapshot = captured[0]
    assert event_type == "SYSTEM_COMMANDER"
    assert snapshot["system_state"] == "HEALTHY"
    assert snapshot["toolchain"]["gh"]["active"] is True
    assert snapshot["toolchain"]["aider"]["active"] is True
    assert snapshot["toolchain"]["copilot"]["active"] is True
    assert snapshot["resources"] == {"cpu": 12.5, "ram": 34.5, "disk": 56.7}
    assert (commander.state_dir / "system_commander_snapshot.json").exists()
