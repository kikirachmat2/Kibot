import json
import pytest
from pathlib import Path
from scripts.healthcheck import check_json_states

def create_valid_base_files(state_dir):
    # Create all required base files in the temp state directory
    (state_dir / "leadlag_alpha.json").write_text(json.dumps({
        "qualified_signals": [], "opportunities": [{"strategy_id": "test"}], "last_run_timestamp": 9999999999.0
    }))
    (state_dir / "scanner_runtime.json").write_text(json.dumps({
        "current_interval": 2.0, "mode": "NORMAL", "telemetry": {"cpu_percent": 0.0}
    }))
    (state_dir / "phantom_scout.json").write_text(json.dumps({
        "active_rpc": "https://api.mainnet-beta.solana.com", "failed_rpcs": []
    }))
    (state_dir / "market_rotation.json").write_text(json.dumps({
        "allocations_pct": {"Indodax": 25.0, "Polymarket": 25.0, "Phantom": 25.0, "CASH_WAIT": 25.0}
    }))
    (state_dir / "punishment_state.json").write_text(json.dumps({
        "schema_version": 1, "status": "idle", "records": {}, "quarantined": []
    }))
    (state_dir / "expected_value.json").write_text(json.dumps({
        "schema_version": 1, "status": "idle", "strategies": {}
    }))

def test_healthcheck_all_healthy(tmp_path, monkeypatch):
    create_valid_base_files(tmp_path)
    
    # Mock KIBOT_HEALTHCHECK_ALLOW_BOOTSTRAP to False to test direct validation
    monkeypatch.setenv("KIBOT_HEALTHCHECK_ALLOW_BOOTSTRAP", "false")
    monkeypatch.setenv("KIBOT_ENV", "prod")
    monkeypatch.setenv("KIBOT_HEALTHCHECK_HISTORY_PATH", str(tmp_path / "history.json"))
    
    # This should execute and complete without raising SystemExit
    check_json_states(tmp_path)

def test_healthcheck_missing_punishment_state(tmp_path, monkeypatch):
    create_valid_base_files(tmp_path)
    (tmp_path / "punishment_state.json").unlink()
    
    monkeypatch.setenv("KIBOT_HEALTHCHECK_ALLOW_BOOTSTRAP", "false")
    monkeypatch.setenv("KIBOT_ENV", "prod")
    monkeypatch.setenv("KIBOT_HEALTHCHECK_HISTORY_PATH", str(tmp_path / "history.json"))
    
    # Should exit with code 10 due to missing required state file and bootstrapping disabled
    with pytest.raises(SystemExit) as exc_info:
        check_json_states(tmp_path)
    assert exc_info.value.code == 10

def test_healthcheck_corrupted_json(tmp_path, monkeypatch):
    create_valid_base_files(tmp_path)
    (tmp_path / "punishment_state.json").write_text("invalid raw json {")
    
    monkeypatch.setenv("KIBOT_HEALTHCHECK_ALLOW_BOOTSTRAP", "false")
    monkeypatch.setenv("KIBOT_ENV", "prod")
    monkeypatch.setenv("KIBOT_HEALTHCHECK_HISTORY_PATH", str(tmp_path / "history.json"))
    
    # Should exit with code 12 due to JSON decoding error
    with pytest.raises(SystemExit) as exc_info:
        check_json_states(tmp_path)
    assert exc_info.value.code == 12

def test_healthcheck_missing_schema_keys_punishment(tmp_path, monkeypatch):
    create_valid_base_files(tmp_path)
    # Valid JSON but missing "records" and "quarantined"
    (tmp_path / "punishment_state.json").write_text(json.dumps({
        "schema_version": 1, "status": "idle"
    }))
    
    monkeypatch.setenv("KIBOT_HEALTHCHECK_ALLOW_BOOTSTRAP", "false")
    monkeypatch.setenv("KIBOT_ENV", "prod")
    monkeypatch.setenv("KIBOT_HEALTHCHECK_HISTORY_PATH", str(tmp_path / "history.json"))
    
    # Should exit with code 18 due to schema keys mismatch
    with pytest.raises(SystemExit) as exc_info:
        check_json_states(tmp_path)
    assert exc_info.value.code == 18

def test_healthcheck_missing_schema_keys_ev(tmp_path, monkeypatch):
    create_valid_base_files(tmp_path)
    # Valid JSON but missing "strategies"
    (tmp_path / "expected_value.json").write_text(json.dumps({
        "schema_version": 1, "status": "idle"
    }))
    
    monkeypatch.setenv("KIBOT_HEALTHCHECK_ALLOW_BOOTSTRAP", "false")
    monkeypatch.setenv("KIBOT_ENV", "prod")
    monkeypatch.setenv("KIBOT_HEALTHCHECK_HISTORY_PATH", str(tmp_path / "history.json"))
    
    # Should exit with code 19 due to schema keys mismatch
    with pytest.raises(SystemExit) as exc_info:
        check_json_states(tmp_path)
    assert exc_info.value.code == 19
