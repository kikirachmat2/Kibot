"""
Unit tests for WatchdogManager.
"""

import os
import time
import pytest
from cluster.watchdog import WatchdogManager


def test_watchdog_heartbeat():
    mgr = WatchdogManager()
    assert mgr.record_heartbeat(True)["status"] == "HEALTHY"

    # 2 missed pings -> unhealthy but no restart yet (MAX_MISSED_PINGS=3)
    for _ in range(2):
        res = mgr.record_heartbeat(False)
    assert res["status"] == "UNHEALTHY"
    assert res["should_restart"] is False

    # 3rd missed ping -> trigger auto-restart
    res3 = mgr.record_heartbeat(False)
    assert res3["should_restart"] is True


def test_watchdog_disk_usage():
    mgr = WatchdogManager()
    usage = mgr.check_disk_usage()
    assert "total_gb" in usage
    assert "used_pct" in usage
    assert isinstance(usage["is_critical"], bool)


def test_database_backup_and_purge(tmp_path):
    db_file = str(tmp_path / "kibot_live.db")
    with open(db_file, "w") as f:
        f.write("mock db content")

    backup_dir = str(tmp_path / "backups")
    mgr = WatchdogManager(backup_dir=backup_dir, db_path=db_file)

    backup_path = mgr.create_database_backup()
    assert os.path.exists(backup_path)

    # Purge with 0 days retention should clean up
    purged = mgr.purge_old_backups(retention_days=-1)
    assert purged == 1
    assert not os.path.exists(backup_path)


def test_watchdog_ping_sg1_and_alert():
    from unittest.mock import patch, MagicMock

    mgr = WatchdogManager(bot_token="test_token", chat_id="12345")

    # 1. Test successful health ping
    mock_resp_data = b'{"status": "HEALTHY", "uptime_seconds": 120.5, "commit_hash": "a4de888"}'
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = mock_resp_data
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = mgr.ping_sg1_health("http://127.0.0.1:8789/health")
        assert res["status"] == "HEALTHY"
        assert res["missed_pings"] == 0
        assert res["details"]["commit_hash"] == "a4de888"

    # 2. Test failed health ping
    with patch("urllib.request.urlopen", side_effect=RuntimeError("Connection refused")):
        res_fail = mgr.ping_sg1_health("http://127.0.0.1:8789/health")
        assert res_fail["status"] == "UNHEALTHY"
        assert res_fail["missed_pings"] == 1
        assert "Connection refused" in str(res_fail["details"])

    # 3. Test independent Telegram alert transmission
    mock_post_resp = MagicMock()
    mock_post_resp.status = 200
    mock_post_resp.__enter__.return_value = mock_post_resp

    with patch("urllib.request.urlopen", return_value=mock_post_resp):
        alert_sent = mgr.send_telegram_alert("🚨 TEST WATCHDOG ALERT")
        assert alert_sent is True

    # 4. Test SSH remote restart command
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0)
        restarted = mgr.restart_remote_service_ssh("100.105.139.21", "kibot_v3")
        assert restarted is True
        assert "sudo systemctl restart kibot_v3" in mock_sub.call_args[0][0]
