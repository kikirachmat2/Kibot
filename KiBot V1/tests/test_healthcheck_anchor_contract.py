#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts import healthcheck

try:
    from Core.Support.ki_config import WIB
except ImportError:
    from datetime import timezone, timedelta

    WIB = timezone(timedelta(hours=7))

from datetime import datetime


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _live_env() -> dict[str, str]:
    return {
        "KIBOT_LIVE_TRADING_ENABLED": "true",
        "KIBOT_CANARY_LIVE_ENABLED": "false",
        "KIBOT_WITHDRAWAL_ENABLED": "false",
        "KIBOT_BLOCK_TRADE_IF_EV_NEGATIVE": "true",
        "KIBOT_BLOCK_TRADE_IF_STATE_STALE": "true",
        "KIBOT_BLOCK_TRADE_IF_KILL_SWITCH": "true",
    }


def test_healthcheck_suppresses_rollback_by_default(monkeypatch):
    monkeypatch.delenv("KIBOT_HEALTHCHECK_ALLOW_ROLLBACK", raising=False)

    with patch.object(subprocess, "run") as mock_run:
        healthcheck.trigger_rollback("unit test failure")

    mock_run.assert_not_called()


def test_healthcheck_failure_does_not_mutate_env_or_kill_switch_by_default(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "KIBOT_LIVE_TRADING_ENABLED=true\nKIBOT_CANARY_LIVE_ENABLED=false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(healthcheck, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("KIBOT_HEALTHCHECK_ALLOW_ROLLBACK", raising=False)

    healthcheck.trigger_rollback("unit test failure")

    assert env_path.read_text(encoding="utf-8") == (
        "KIBOT_LIVE_TRADING_ENABLED=true\nKIBOT_CANARY_LIVE_ENABLED=false\n"
    )
    assert not (tmp_path / "state" / "KILL_SWITCH").exists()


def test_healthcheck_rollback_requires_explicit_flag(tmp_path, monkeypatch):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "rollback.py").write_text("print('rollback')\n", encoding="utf-8")
    monkeypatch.setattr(healthcheck, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("KIBOT_HEALTHCHECK_ALLOW_ROLLBACK", "true")

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.stdout = "rollback ok"
        mock_run.return_value.stderr = ""
        healthcheck.trigger_rollback("unit test failure")

    mock_run.assert_called_once()


def test_stale_anchor_lock_does_not_override_current_primary_anchor(tmp_path, monkeypatch):
    today_wib = str(datetime.now(WIB).date())
    state_dir = tmp_path / "state"
    _write_json(
        state_dir / "daily_equity_anchor.json",
        {
            "date": today_wib,
            "start_equity_idr": 250000.0,
            "max_daily_loss_pct": 1.5,
            "max_daily_loss_idr": 3750.0,
        },
    )
    _write_json(
        state_dir / "daily_equity_anchor_lock.json",
        {
            "date": "2026-05-27",
            "start_equity_idr": 177155.27,
            "max_daily_loss_pct": 1.5,
            "max_daily_loss_idr": 2657.33,
        },
    )
    _write_json(
        state_dir / "active_strategy.json",
        {"indodax": {"trailing_stop_pct": 0.5, "hard_stop_pct": 1.5}},
    )

    monkeypatch.setattr(healthcheck, "PROJECT_ROOT", tmp_path)
    config = SimpleNamespace(LIVE_TRADING_ENABLED=False)

    with patch("scripts.healthcheck.safe_exit") as mock_exit, patch.dict(
        "os.environ",
        _live_env(),
        clear=False,
    ):
        healthcheck.check_live_trading_gates(config)

    mock_exit.assert_not_called()


def test_current_anchor_lock_still_takes_precedence(tmp_path, monkeypatch):
    today_wib = str(datetime.now(WIB).date())
    state_dir = tmp_path / "state"
    _write_json(
        state_dir / "daily_equity_anchor.json",
        {
            "date": today_wib,
            "start_equity_idr": 250000.0,
            "max_daily_loss_pct": 1.5,
            "max_daily_loss_idr": 3750.0,
        },
    )
    _write_json(
        state_dir / "daily_equity_anchor_lock.json",
        {
            "date": today_wib,
            "start_equity_idr": 177155.27,
            "max_daily_loss_pct": 2.0,
            "max_daily_loss_idr": 3543.11,
        },
    )
    _write_json(
        state_dir / "active_strategy.json",
        {"indodax": {"trailing_stop_pct": 0.5, "hard_stop_pct": 1.5}},
    )

    monkeypatch.setattr(healthcheck, "PROJECT_ROOT", tmp_path)
    config = SimpleNamespace(LIVE_TRADING_ENABLED=False)

    with patch("scripts.healthcheck.safe_exit") as mock_exit, patch.dict(
        "os.environ",
        _live_env(),
        clear=False,
    ):
        mock_exit.side_effect = SystemExit
        with pytest.raises(SystemExit):
            healthcheck.check_live_trading_gates(config)

    mock_exit.assert_called_with(33, "daily_equity_anchor.json max_daily_loss_pct must be exactly 1.5%!")
