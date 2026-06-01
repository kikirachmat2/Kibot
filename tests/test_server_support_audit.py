from __future__ import annotations

from Core.Support import money_movement_audit


def test_server_support_audit_handles_systemctl_result(monkeypatch) -> None:
    class Result:
        stdout = "active active active active active active"

    monkeypatch.setattr(money_movement_audit.subprocess, "run", lambda *a, **k: Result())
    result = money_movement_audit.server_support_audit({"server_telemetry": {"cpu": 1}})
    assert "server_support_status" in result

