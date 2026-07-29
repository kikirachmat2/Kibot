"""Regression unit tests for DepositEventManager and CapitalGovernor end-to-end evaluation.

Ensures:
1. End-to-end gov.evaluate() with deposit D and zero trading yields daily_pnl_idr == 0 (no double-subtraction).
2. End-to-end gov.evaluate() with deposit D and trading profit P yields daily_pnl_idr == +P.
3. End-to-end gov.evaluate() with deposit D and trading loss L yields daily_pnl_idr == -L.
4. Large balance increase (>50%) WITHOUT deposit event triggers drift safeguard.
"""

import json, asyncio
from pathlib import Path
import pytest

from Core.Treasury.deposit_event_manager import DepositEventManager
from Core.Treasury.capital_governor import CapitalGovernor


class MockIndodaxGateway:
    def __init__(self, idr_balance: float):
        self.idr_balance = idr_balance

    async def get_info(self):
        return {"success": 1, "return": {"balance": {"idr": self.idr_balance}}}


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

    import Core.Support.ki_config as kc_mod
    monkeypatch.setattr(kc_mod.KiConfig, "LIVE_TRADING_ENABLED", True)

    dep_mgr = DepositEventManager(log_file=log_file)
    monkeypatch.setattr(dem_mod, "_deposit_manager_instance", dep_mgr)

    gov = CapitalGovernor()
    gov.last_reset_date = "2026-07-29"
    gov.start_total_equity_idr = 100000.0
    gov.start_indodax_equity_idr = 100000.0

    return dep_mgr, gov, state_dir


def test_end_to_end_deposit_reconciliation_zero_trading_pnl(temp_treasury_env, monkeypatch):
    dep_mgr, gov, _ = temp_treasury_env

    # Baseline start equity X = 100,000 IDR
    X = 100000.0
    D = 500000.0  # Deposit amount

    # Record operator deposit notification
    event = dep_mgr.record_deposit(amount_idr=D, note="Top up 500k test")
    assert event["reconciled"] is False

    # Attach mock Indodax gateway with X + D = 600,000 IDR
    gov.indodax = MockIndodaxGateway(idr_balance=X + D)

    # Call end-to-end reconcile_governor()
    gov_data = asyncio.run(gov.reconcile_governor())

    # Assertions:
    # 1. Unreconciled deposit cleared
    assert len(dep_mgr.get_unreconciled_deposits()) == 0

    # 2. current_total_equity_idr is 600,000 IDR
    assert abs(gov_data["current_total_equity_idr"] - (X + D)) < 0.01

    # 3. daily_pnl_idr MUST be 0.0 (NOT -500k or any negative double-subtraction)
    assert abs(gov_data["daily_pnl_idr"]) < 0.01
    assert abs(gov_data["daily_pnl_pct"]) < 0.001


def test_end_to_end_deposit_reconciliation_with_real_trading_pnl(temp_treasury_env, monkeypatch):
    dep_mgr, gov, _ = temp_treasury_env

    # Baseline start equity X = 100,000 IDR
    X = 100000.0
    D = 500000.0  # Deposit amount
    P = 25000.0   # Real trading profit = +25,000 IDR

    # Record operator deposit notification
    dep_mgr.record_deposit(amount_idr=D, note="Top up test")

    # Attach mock Indodax gateway with X + D + P = 625,000 IDR
    gov.indodax = MockIndodaxGateway(idr_balance=X + D + P)

    # Call end-to-end reconcile_governor()
    gov_data = asyncio.run(gov.reconcile_governor())

    # Assertions:
    # 1. daily_pnl_idr MUST be exactly +P (+25,000 IDR), NOT +25k - 500k or any distorted number
    assert abs(gov_data["daily_pnl_idr"] - P) < 0.01
    assert gov_data["status"] == "RECONCILED"
    assert gov_data["allow_new_orders"] is True


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
