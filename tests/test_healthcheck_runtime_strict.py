#!/usr/bin/env python3
import os
import sys
import json
import time
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Ensure project root is in the path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from scripts.healthcheck import check_json_states

def test_healthcheck_missing_state_in_production(tmp_path):
    # In production, bootstrapping is disabled. Missing files must trigger sys.exit(10) or safe_exit
    with patch("scripts.healthcheck.safe_exit") as mock_exit, \
         patch.dict(os.environ, {
             "KIBOT_ENV": "production",
             "KIBOT_HEALTHCHECK_HISTORY_PATH": str(tmp_path / "history.json")
         }):
        mock_exit.side_effect = SystemExit
        with pytest.raises(SystemExit):
            check_json_states(tmp_path)
        
        # Verify safe_exit was called with exit code 10 due to missing required files
        mock_exit.assert_called_with(10, "Required state file leadlag_alpha.json is missing, and bootstrapping is disabled!")

def test_healthcheck_stale_state(tmp_path):
    # Write a stale scanner_runtime.json file
    scanner_file = tmp_path / "scanner_runtime.json"
    leadlag_file = tmp_path / "leadlag_alpha.json"
    market_file = tmp_path / "market_rotation.json"
    
    # Write fresh leadlag and market rotation files
    leadlag_file.write_text(json.dumps({"mode": "NORMAL", "opportunities": [{"pair": "BTC/USDT"}]}))
    market_file.write_text(json.dumps({"allocations_pct": {}}))
    
    # Write stale scanner file
    scanner_file.write_text(json.dumps({"mode": "NORMAL", "qualified_signals": [], "allocations_pct": {}}))
    os.utime(scanner_file, (time.time() - 100, time.time() - 100))
        
    with patch("scripts.healthcheck.safe_exit") as mock_exit, \
         patch.dict(os.environ, {
             "KIBOT_ENV": "production",
             "KIBOT_HEALTHCHECK_HISTORY_PATH": str(tmp_path / "history.json")
         }):
         
        check_json_states(tmp_path)
        mock_exit.assert_called_with(11, f"scanner_runtime.json is stale! Last modified 100.0s ago (limit: 90.0s).")

def test_healthcheck_invalid_json(tmp_path):
    # Write corrupt JSON
    scanner_file = tmp_path / "scanner_runtime.json"
    leadlag_file = tmp_path / "leadlag_alpha.json"
    market_file = tmp_path / "market_rotation.json"
    
    scanner_file.write_text("NOT_JSON")
    leadlag_file.write_text("{}")
    market_file.write_text("{}")
    
    with patch("scripts.healthcheck.safe_exit") as mock_exit, \
         patch.dict(os.environ, {
             "KIBOT_ENV": "production",
             "KIBOT_HEALTHCHECK_HISTORY_PATH": str(tmp_path / "history.json")
         }):
         
        check_json_states(tmp_path)
        # Should raise JSONDecodeError exit 12
        mock_exit.assert_called_with(12, f"scanner_runtime.json has invalid JSON syntax: Expecting value: line 1 column 1 (char 0)")
