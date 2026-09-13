import json
import time
from pathlib import Path
import pytest
from Core.Intelligence.punishment_engine import PunishmentEngine, StrategyRecord

def test_punishment_engine_baseline_creation(tmp_path):
    state_file = tmp_path / "punishment_state.json"
    assert not state_file.exists()

    engine = PunishmentEngine(state_file=state_file)
    assert state_file.exists()

    data = json.loads(state_file.read_text())
    assert data["status"] == "idle"
    assert data["records"] == {}
    assert data["quarantined"] == []
    assert "updated_at" in data
    assert data["schema_version"] == 1
    assert not engine.corrupted_state_active

def test_punishment_engine_corruption_recovery(tmp_path):
    state_file = tmp_path / "punishment_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("invalid json { corrupt }")

    engine = PunishmentEngine(state_file=state_file)
    assert engine.corrupted_state_active

    # Check baseline was re-written
    data = json.loads(state_file.read_text())
    assert data["status"] == "idle"
    assert data["schema_version"] == 1

    # Check corrupted backup exists
    corrupt_backups = list(tmp_path.glob("punishment_state.corrupt.*.json"))
    assert len(corrupt_backups) == 1
    assert corrupt_backups[0].read_text() == "invalid json { corrupt }"

    # Check quarantine is enforced due to corruption
    assert engine.is_quarantined("strategy_a") is True
    assert engine.get_severity("strategy_a") == 1.0

def test_punishment_engine_backward_compatibility(tmp_path):
    state_file = tmp_path / "punishment_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Write old format
    old_data = {
        "strategy_a": {
            "strategy_id": "strategy_a",
            "loss_streak": 2,
            "daily_pnl": -0.01,
            "quarantine_until": 0.0,
            "severity": 0.5,
            "total_trades": 10,
            "total_wins": 5,
            "total_losses": 5
        }
    }
    state_file.write_text(json.dumps(old_data, indent=2))

    engine = PunishmentEngine(state_file=state_file)
    assert not engine.corrupted_state_active
    assert engine.get_severity("strategy_a") == 0.5
    assert engine.is_quarantined("strategy_a") is False

    # Perform a trade record to trigger _save in the new format
    engine.record_trade("strategy_a", 0.01)
    
    # Read saved file and verify new format
    saved_data = json.loads(state_file.read_text())
    assert saved_data["schema_version"] == 1
    assert "records" in saved_data
    assert "strategy_a" in saved_data["records"]
    assert saved_data["records"]["strategy_a"]["total_trades"] == 11
