from __future__ import annotations

from Core.Support import money_movement_audit


def test_server_support_degrades_when_backups_or_stale_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(money_movement_audit, "STATE_DIR", tmp_path)

    class Result:
        stdout = "active active active active active active"

    monkeypatch.setattr(money_movement_audit.subprocess, "run", lambda *a, **k: Result())
    result = money_movement_audit.server_support_audit({"server_telemetry": {"cpu": 1}, "no_trade_forensics": {"ignored_stale_blockers": [{"source": "x"}]}})
    assert result["server_support_status"] in {"WARN", "FAIL"}

