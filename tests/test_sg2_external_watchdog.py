"""Unit tests for KiBot SG2 External Sentinel Watchdog."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.sg2_external_watchdog import (
    ExternalWatchdogSentinel,
    probe_sg1_status,
    send_telegram_alert,
)


def test_send_telegram_alert(monkeypatch):
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        success = send_telegram_alert("test_token", "12345", "Test alert")
        assert success is True

    # Test missing credentials
    assert send_telegram_alert("", "12345", "Test") is False


def test_probe_sg1_status(monkeypatch):
    # Mock healthy output
    mock_proc = MagicMock()
    mock_proc.stdout = "SVC:active\nUDP:listening\n"
    mock_proc.returncode = 0

    with patch("subprocess.run", return_value=mock_proc):
        is_healthy, details = probe_sg1_status("127.0.0.1", "key.pem")
        assert is_healthy is True
        assert details["svc_active"] is True
        assert details["udp_listening"] is True

    # Mock inactive output
    mock_proc.stdout = "SVC:inactive\nUDP:down\n"
    with patch("subprocess.run", return_value=mock_proc):
        is_healthy, details = probe_sg1_status("127.0.0.1", "key.pem")
        assert is_healthy is False
        assert details["svc_active"] is False


def test_sentinel_state_machine(tmp_path):
    state_dir = tmp_path / "state"
    backup_dir = tmp_path / "backups"

    sentinel = ExternalWatchdogSentinel(
        sg1_host="127.0.0.1",
        ssh_key="key.pem",
        state_dir=state_dir,
        backup_dir=backup_dir,
        down_threshold_sec=60.0,
        backup_interval_sec=3600.0,
        telegram_token="dummy_token",
        telegram_chat_id="dummy_chat",
    )

    t0 = 1000.0

    # 1. Cycle 1: SG1 is healthy -> Backup triggered initially since last_backup_ts=0
    with patch("scripts.sg2_external_watchdog.probe_sg1_status", return_value=(True, {"raw": "ok"})):
        with patch("scripts.sg2_external_watchdog.execute_backup_mirror", return_value=(True, "ok")):
            res = sentinel.evaluate_cycle(now=t0)
            assert res["is_healthy"] is True
            assert res["backup_performed"] is True
            assert sentinel.state["status"] == "ok"
            assert sentinel.state["down_since"] is None

    # 2. Cycle 2: SG1 becomes unhealthy -> downtime recorded, alert NOT yet sent (under threshold)
    with patch("scripts.sg2_external_watchdog.probe_sg1_status", return_value=(False, {"raw": "down"})):
        res = sentinel.evaluate_cycle(now=t0 + 10.0)
        assert res["is_healthy"] is False
        assert res["alert_sent"] is False
        assert sentinel.state["down_since"] == t0 + 10.0
        assert sentinel.state["alert_sent"] is False

    # 3. Cycle 3: SG1 still down after 65 seconds (>= down_threshold_sec) -> Alert sent!
    with patch("scripts.sg2_external_watchdog.probe_sg1_status", return_value=(False, {"raw": "down"})):
        with patch("scripts.sg2_external_watchdog.send_telegram_alert", return_value=True):
            res = sentinel.evaluate_cycle(now=t0 + 75.0)
            assert res["is_healthy"] is False
            assert res["alert_sent"] is True
            assert sentinel.state["alert_sent"] is True

    # 4. Cycle 4: SG1 recovers -> Recovery notification sent!
    with patch("scripts.sg2_external_watchdog.probe_sg1_status", return_value=(True, {"raw": "ok"})):
        with patch("scripts.sg2_external_watchdog.send_telegram_alert", return_value=True):
            res = sentinel.evaluate_cycle(now=t0 + 90.0)
            assert res["is_healthy"] is True
            assert res["recovery_sent"] is True
            assert sentinel.state["status"] == "ok"
            assert sentinel.state["down_since"] is None
            assert sentinel.state["alert_sent"] is False
