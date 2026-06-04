#!/usr/bin/env python3
import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from datetime import datetime

# Ensure project root is in the path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from scripts.healthcheck import check_live_trading_gates

try:
    from Core.Support.ki_config import WIB
except ImportError:
    from datetime import timezone, timedelta
    WIB = timezone(timedelta(hours=7))

@pytest.fixture
def mock_state_dir(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir

def test_healthcheck_live_trading_enabled_error(mock_state_dir):
    # KIBOT_LIVE_TRADING_ENABLED=false should fail with code 30
    with patch("scripts.healthcheck.safe_exit") as mock_exit, \
         patch("scripts.healthcheck.PROJECT_ROOT", mock_state_dir.parent), \
         patch.dict(os.environ, {
             "KIBOT_LIVE_TRADING_ENABLED": "false",
             "KIBOT_CANARY_LIVE_ENABLED": "false"
         }):
        mock_exit.side_effect = SystemExit
        with pytest.raises(SystemExit):
            check_live_trading_gates(MagicMock())
        mock_exit.assert_called_with(30, "KIBOT_LIVE_TRADING_ENABLED must be True in LIVE_ONLY mode.")

def test_healthcheck_canary_disabled_error(mock_state_dir):
    # KIBOT_CANARY_LIVE_ENABLED=true should fail with code 31
    with patch("scripts.healthcheck.safe_exit") as mock_exit, \
         patch("scripts.healthcheck.PROJECT_ROOT", mock_state_dir.parent), \
         patch.dict(os.environ, {
             "KIBOT_LIVE_TRADING_ENABLED": "true",
             "KIBOT_CANARY_LIVE_ENABLED": "true"
         }):
        mock_exit.side_effect = SystemExit
        with pytest.raises(SystemExit):
            check_live_trading_gates(MagicMock())
        mock_exit.assert_called_with(31, "KIBOT_CANARY_LIVE_ENABLED must be False in LIVE_ONLY mode.")

def test_healthcheck_missing_safety_gates(mock_state_dir):
    # Missing any required safety gate (e.g. KIBOT_BLOCK_TRADE_IF_EV_NEGATIVE=false) should fail with code 32
    with patch("scripts.healthcheck.safe_exit") as mock_exit, \
         patch("scripts.healthcheck.PROJECT_ROOT", mock_state_dir.parent), \
         patch.dict(os.environ, {
             "KIBOT_LIVE_TRADING_ENABLED": "true",
             "KIBOT_CANARY_LIVE_ENABLED": "false",
             "KIBOT_BLOCK_TRADE_IF_EV_NEGATIVE": "false",
             "KIBOT_BLOCK_TRADE_IF_STATE_STALE": "true",
             "KIBOT_BLOCK_TRADE_IF_KILL_SWITCH": "true"
         }):
        mock_exit.side_effect = SystemExit
        with pytest.raises(SystemExit):
            check_live_trading_gates(MagicMock())
        mock_exit.assert_called_with(32, "Environment safety gate KIBOT_BLOCK_TRADE_IF_EV_NEGATIVE must be enabled!")

def test_healthcheck_missing_equity_anchor(mock_state_dir):
    # Missing daily_equity_anchor.json should fail with code 33
    with patch("scripts.healthcheck.safe_exit") as mock_exit, \
         patch("scripts.healthcheck.PROJECT_ROOT", mock_state_dir.parent), \
         patch.dict(os.environ, {
             "KIBOT_LIVE_TRADING_ENABLED": "true",
             "KIBOT_CANARY_LIVE_ENABLED": "false",
             "KIBOT_BLOCK_TRADE_IF_EV_NEGATIVE": "true",
             "KIBOT_BLOCK_TRADE_IF_STATE_STALE": "true",
             "KIBOT_BLOCK_TRADE_IF_KILL_SWITCH": "true"
         }):
        mock_exit.side_effect = SystemExit
        with pytest.raises(SystemExit):
            check_live_trading_gates(MagicMock())
        mock_exit.assert_called_with(33, "daily_equity_anchor.json is missing!")

def test_healthcheck_stale_equity_anchor(mock_state_dir):
    # Stale daily_equity_anchor.json (different date) should fail with code 33
    anchor_file = mock_state_dir / "daily_equity_anchor.json"
    with open(anchor_file, "w") as f:
        json.dump({"date": "2020-01-01", "max_daily_loss_pct": 1.5}, f)

    with patch("scripts.healthcheck.safe_exit") as mock_exit, \
         patch("scripts.healthcheck.PROJECT_ROOT", mock_state_dir.parent), \
         patch.dict(os.environ, {
             "KIBOT_LIVE_TRADING_ENABLED": "true",
             "KIBOT_CANARY_LIVE_ENABLED": "false",
             "KIBOT_BLOCK_TRADE_IF_EV_NEGATIVE": "true",
             "KIBOT_BLOCK_TRADE_IF_STATE_STALE": "true",
             "KIBOT_BLOCK_TRADE_IF_KILL_SWITCH": "true"
         }):
        mock_exit.side_effect = SystemExit
        with pytest.raises(SystemExit):
            check_live_trading_gates(MagicMock())
        # Correctly assert dynamic exit
        args, _ = mock_exit.call_args
        assert args[0] == 33
        assert "is stale" in args[1]

def test_healthcheck_invalid_loss_pct_anchor(mock_state_dir):
    # daily_equity_anchor.json with non-1.5% max_daily_loss_pct should fail with code 33
    today_wib = str(datetime.now(WIB).date())
    anchor_file = mock_state_dir / "daily_equity_anchor.json"
    with open(anchor_file, "w") as f:
        json.dump({"date": today_wib, "max_daily_loss_pct": 2.5}, f)

    with patch("scripts.healthcheck.safe_exit") as mock_exit, \
         patch("scripts.healthcheck.PROJECT_ROOT", mock_state_dir.parent), \
         patch.dict(os.environ, {
             "KIBOT_LIVE_TRADING_ENABLED": "true",
             "KIBOT_CANARY_LIVE_ENABLED": "false",
             "KIBOT_BLOCK_TRADE_IF_EV_NEGATIVE": "true",
             "KIBOT_BLOCK_TRADE_IF_STATE_STALE": "true",
             "KIBOT_BLOCK_TRADE_IF_KILL_SWITCH": "true"
         }):
        mock_exit.side_effect = SystemExit
        with pytest.raises(SystemExit):
            check_live_trading_gates(MagicMock())
        mock_exit.assert_called_with(33, "daily_equity_anchor.json max_daily_loss_pct must be exactly 1.5%!")

def test_healthcheck_missing_active_strategy(mock_state_dir):
    # Missing active_strategy.json should fail with code 34
    today_wib = str(datetime.now(WIB).date())
    anchor_file = mock_state_dir / "daily_equity_anchor.json"
    with open(anchor_file, "w") as f:
        json.dump({"date": today_wib, "max_daily_loss_pct": 1.5}, f)

    with patch("scripts.healthcheck.safe_exit") as mock_exit, \
         patch("scripts.healthcheck.PROJECT_ROOT", mock_state_dir.parent), \
         patch.dict(os.environ, {
             "KIBOT_LIVE_TRADING_ENABLED": "true",
             "KIBOT_CANARY_LIVE_ENABLED": "false",
             "KIBOT_BLOCK_TRADE_IF_EV_NEGATIVE": "true",
             "KIBOT_BLOCK_TRADE_IF_STATE_STALE": "true",
             "KIBOT_BLOCK_TRADE_IF_KILL_SWITCH": "true"
         }):
        mock_exit.side_effect = SystemExit
        with pytest.raises(SystemExit):
            check_live_trading_gates(MagicMock())
        mock_exit.assert_called_with(34, "active_strategy.json is missing!")

def test_healthcheck_invalid_active_strategy(mock_state_dir):
    # active_strategy.json missing SL/TP parameter should fail with code 34
    today_wib = str(datetime.now(WIB).date())
    anchor_file = mock_state_dir / "daily_equity_anchor.json"
    with open(anchor_file, "w") as f:
        json.dump({"date": today_wib, "max_daily_loss_pct": 1.5}, f)
        
    strategy_file = mock_state_dir / "active_strategy.json"
    with open(strategy_file, "w") as f:
        json.dump({"indodax": {"trailing_stop_pct": 0.0, "hard_stop_pct": 1.5}}, f)

    with patch("scripts.healthcheck.safe_exit") as mock_exit, \
         patch("scripts.healthcheck.PROJECT_ROOT", mock_state_dir.parent), \
         patch.dict(os.environ, {
             "KIBOT_LIVE_TRADING_ENABLED": "true",
             "KIBOT_CANARY_LIVE_ENABLED": "false",
             "KIBOT_BLOCK_TRADE_IF_EV_NEGATIVE": "true",
             "KIBOT_BLOCK_TRADE_IF_STATE_STALE": "true",
             "KIBOT_BLOCK_TRADE_IF_KILL_SWITCH": "true"
         }):
        mock_exit.side_effect = SystemExit
        with pytest.raises(SystemExit):
            check_live_trading_gates(MagicMock())
        mock_exit.assert_called_with(34, "Active risk configuration is missing trailing_stop_pct or hard_stop_pct!")

def test_healthcheck_all_gates_pass(mock_state_dir):
    # All checks passing should execute cleanly without calling exit
    today_wib = str(datetime.now(WIB).date())
    anchor_file = mock_state_dir / "daily_equity_anchor.json"
    with open(anchor_file, "w") as f:
        json.dump({"date": today_wib, "max_daily_loss_pct": 1.5}, f)
        
    strategy_file = mock_state_dir / "active_strategy.json"
    with open(strategy_file, "w") as f:
        json.dump({"indodax": {"trailing_stop_pct": 0.5, "hard_stop_pct": 1.5}}, f)

    with patch("scripts.healthcheck.safe_exit") as mock_exit, \
         patch("scripts.healthcheck.PROJECT_ROOT", mock_state_dir.parent), \
         patch.dict(os.environ, {
             "KIBOT_LIVE_TRADING_ENABLED": "true",
             "KIBOT_CANARY_LIVE_ENABLED": "false",
             "KIBOT_BLOCK_TRADE_IF_EV_NEGATIVE": "true",
             "KIBOT_BLOCK_TRADE_IF_STATE_STALE": "true",
             "KIBOT_BLOCK_TRADE_IF_KILL_SWITCH": "true"
         }):
        check_live_trading_gates(MagicMock())
        mock_exit.assert_not_called()
