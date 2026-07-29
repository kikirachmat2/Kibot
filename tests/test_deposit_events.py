"""Unit tests for DepositEventManager and CapitalGovernor integration.

Tests:
1. Operator deposit event notification increases start_total_equity_idr and start_indodax_equity_idr without inflating daily PnL.
2. Large balance increase (>50%) WITHOUT deposit event triggers safeguard drift warning.
"""

import json
from pathlib import Path
import pytest

from Core.Treasury.deposit_event_manager import DepositEventManager
from Core.Treasury.capital_governor import CapitalGovernor


@pytest.fixture
def temp_treasury_env(tmp_path, monkeypatch):
    import Core.Treasury.deposit_event_manager as dem_mod
    import Core.Treasury.capital_governor as cg_mod

    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    log_file = state_dir / "deposit_events.jsonl"
    anchor_file = state_dir / "daily_equity_anchor.json"
    governor_file = state_dir / "capital_governor.json"

    monkeypatch.setattr(dem_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(dem_mod, "DEPOSIT_LOG_FILE", log_file)

    monkeypatch.setattr(cg_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(cg_mod, "ANCHOR_FILE", anchor_file)
    monkeypatch.setattr(cg_mod, "GOVERNOR_FILE", governor_file)

    dep_mgr = DepositEventManager(log_file=log_file)
    monkeypatch.setattr(dem_mod, "_deposit_manager_instance", dep_mgr)
    gov = CapitalGovernor()
    gov.last_reset_date = "2026-07-29"
    gov.start_total_equity_idr = 100000.0
    gov.start_indodax_equity_idr = 100000.0

    return dep_mgr, gov, state_dir


def test_operator_deposit_event_reconciliation(temp_treasury_env):
    dep_mgr, gov, state_dir = temp_treasury_env

    initial_start_equity = gov.start_total_equity_idr  # 100,000 IDR

    # 1. Record deposit notification of 500,000 IDR
    event = dep_mgr.record_deposit(amount_idr=500000.0, note="Operator manual topup test")
    assert event["reconciled"] is False
    assert len(dep_mgr.get_unreconciled_deposits()) == 1

    # 2. CapitalGovernor reconciles transfers
    deposits, _ = gov._read_daily_transfers("2026-07-29")
    assert deposits == 500000.0

    # 3. Verify start equity updated and unreconciled deposit cleared
    assert gov.start_total_equity_idr == 600000.0  # 100k + 500k
    assert gov.start_indodax_equity_idr == 600000.0
    assert len(dep_mgr.get_unreconciled_deposits()) == 0

    # 4. Verify PnL is NOT inflated as profit when equity matches new start equity
    gov.current_total_equity_idr = 600000.0
    gov.daily_pnl_idr = gov.current_total_equity_idr - gov.start_total_equity_idr
    # Since start_equity was updated to 600k and current equity is 600k, PnL = 600k - 600k = 0
    assert gov.daily_pnl_idr == 0.0


def test_large_balance_increase_without_deposit_event_drift_safeguard(temp_treasury_env, caplog):
    _, gov, state_dir = temp_treasury_env

    # Initial anchor equity set to 100,000 IDR
    anchor_file = state_dir / "daily_equity_anchor.json"
    anchor_file.write_text(json.dumps({
        "date": "2026-07-29",
        "start_equity_idr": 100000.0,
        "max_daily_loss_pct": 3.0,
        "max_daily_loss_idr": 3000.0,
        "source": "capital_governor"
    }))

    # Propose new anchor equity of 300,000 IDR (>50% increase) WITHOUT deposit event
    gov.start_total_equity_idr = 300000.0
    gov._write_daily_anchor(force=False)

    # Verify existing baseline 100,000 IDR preserved due to 50% drift safeguard
    anchor_data = json.loads(anchor_file.read_text())
    assert anchor_data["start_equity_idr"] == 100000.0
    assert "deposit-notify" in caplog.text.lower()
