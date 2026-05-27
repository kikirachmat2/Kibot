import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import Core.Decision.daily_reset_coordinator as daily_reset_coordinator
import Core.sovereign_state as sovereign_state
import Core.Treasury.capital_governor as capital_module
import Core.Treasury.venue_ledger as ledger_module
import Core.Treasury.phantom_treasury as phantom_module

from Core.Support.ki_config import WIB
from Core.Treasury.capital_governor import CapitalGovernor
from Core.sovereign_state import load_strategy


def _isolate_runtime_state(monkeypatch, tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(capital_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(capital_module, "GOVERNOR_FILE", tmp_path / "capital_governor.json")
    monkeypatch.setattr(capital_module, "ANCHOR_FILE", tmp_path / "daily_equity_anchor.json")
    monkeypatch.setattr(ledger_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(ledger_module, "LEDGER_FILE", tmp_path / "venue_ledger.json")
    monkeypatch.setattr(phantom_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(phantom_module, "PHANTOM_STATE_FILE", tmp_path / "phantom_treasury.json")
    monkeypatch.setattr(phantom_module, "PHANTOM_RECONCILIATION_FILE", tmp_path / "TREASURY_RECONCILIATION_REQUIRED")
    monkeypatch.setattr(daily_reset_coordinator, "STATE_DIR", tmp_path)
    monkeypatch.setattr(daily_reset_coordinator, "STATE_FILE", tmp_path / "daily_reset_state.json")
    monkeypatch.setattr(sovereign_state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(sovereign_state, "STRATEGY_FILE", tmp_path / "active_strategy.json")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_load_strategy_preserves_exit_all(monkeypatch, tmp_path):
    _isolate_runtime_state(monkeypatch, tmp_path)
    _write_json(tmp_path / "active_strategy.json", {
        "global_mode": "EXIT_ALL",
        "indodax": {"allowed_pairs": ["*"]},
    })

    strategy = load_strategy()

    assert strategy["global_mode"] == "EXIT_ALL"


@pytest.mark.anyio
async def test_daily_reset_waits_for_flat_inventory_then_resets(monkeypatch, tmp_path):
    _isolate_runtime_state(monkeypatch, tmp_path)
    today = datetime.now(WIB).date()
    yesterday = today - timedelta(days=1)

    _write_json(tmp_path / "active_strategy.json", {
        "global_mode": "LIVE_AUTONOMOUS_TRADING",
        "daily_state": {"color": "GREEN"},
        "indodax": {"allowed_pairs": ["*"]},
    })
    _write_json(tmp_path / "capital_governor.json", {
        "date": str(yesterday),
        "start_total_equity_idr": 100_000,
        "max_daily_loss_idr": 1_500,
        "status": "RECONCILED",
        "daily_reset_pending": False,
        "allow_new_orders": True,
        "allow_new_orders_reason": "",
    })
    _write_json(tmp_path / "daily_equity_anchor.json", {
        "date": str(yesterday),
        "start_equity_idr": 100_000,
        "max_daily_loss_pct": 1.5,
        "max_daily_loss_idr": 1_500,
        "source": "capital_governor",
    })

    monkeypatch.setattr(capital_module, "load_daily_inventory_snapshot", lambda: {
        "has_open_inventory": True,
        "open_count": 1,
        "open_symbols": ["EDEN"],
        "open_sources": {"active_trades": 1},
        "errors": [],
    })

    governor = CapitalGovernor(None, None)
    governor.current_total_equity_idr = 123_456.0

    await governor.check_daily_reset(governor.current_total_equity_idr)
    data = json.loads((tmp_path / "capital_governor.json").read_text(encoding="utf-8"))
    assert data["daily_reset_pending"] is True
    assert data["status"] == "BLOCKED_WITH_REASON"
    assert data["date"] == str(yesterday)

    monkeypatch.setattr(capital_module, "load_daily_inventory_snapshot", lambda: {
        "has_open_inventory": False,
        "open_count": 0,
        "open_symbols": [],
        "open_sources": {},
        "errors": [],
    })

    governor.pending_daily_reset = True
    await governor.check_daily_reset(governor.current_total_equity_idr)
    data = json.loads((tmp_path / "capital_governor.json").read_text(encoding="utf-8"))
    assert data["daily_reset_pending"] is False
    assert data["status"] in {"RECONCILED", "UNRECONCILED"}
    assert data["date"] == str(today)
    assert data["start_total_equity_idr"] == pytest.approx(123_456.0)


def test_load_daily_inventory_snapshot_ignores_dust_residuals(monkeypatch, tmp_path):
    _isolate_runtime_state(monkeypatch, tmp_path)
    _write_json(tmp_path / "active_trades.json", {
        "PEPE/IDR": {
            "amount": 0.7328859,
            "price": 0.066344,
            "exit_blocked_reason": "EXIT_MINIMUM_NOT_MET: live 0.73288590 PEPE worth Rp0; min coin 152546, min base Rp10,000",
        }
    })

    snapshot = capital_module.load_daily_inventory_snapshot(tmp_path)

    assert snapshot["has_open_inventory"] is False
    assert snapshot["open_count"] == 0
    assert snapshot["residual_count"] == 1
    assert snapshot["residual_symbols"] == ["PEPE/IDR"]


def test_load_daily_inventory_snapshot_quarantines_exchange_locked_inventory(monkeypatch, tmp_path):
    _isolate_runtime_state(monkeypatch, tmp_path)
    _write_json(tmp_path / "active_trades.json", {
        "POND/IDR": {
            "amount": 556.0,
            "price": 112.5,
            "route_status": "BLOCKED_WITH_REASON",
            "exit_blocked_reason": "EXIT_ROUTE_TEMPORARILY_UNAVAILABLE: pond_idr maintenance=1 suspended=0",
        }
    })

    snapshot = capital_module.load_daily_inventory_snapshot(tmp_path)

    assert snapshot["has_open_inventory"] is False
    assert snapshot["open_count"] == 0
    assert snapshot["locked_count"] == 1
    assert snapshot["locked_symbols"] == ["POND/IDR"]


@pytest.mark.anyio
async def test_daily_reset_does_not_freeze_on_exchange_locked_inventory(monkeypatch, tmp_path):
    _isolate_runtime_state(monkeypatch, tmp_path)
    today = datetime.now(WIB).date()
    yesterday = today - timedelta(days=1)
    _write_json(tmp_path / "capital_governor.json", {
        "date": str(yesterday),
        "start_total_equity_idr": 100_000,
        "max_daily_loss_idr": 1_500,
        "status": "RECONCILED",
        "daily_reset_pending": True,
        "allow_new_orders": False,
        "allow_new_orders_reason": "daily_rollover_exit_pending",
    })
    monkeypatch.setattr(capital_module, "load_daily_inventory_snapshot", lambda: {
        "has_open_inventory": False,
        "open_count": 0,
        "open_symbols": [],
        "locked_count": 1,
        "locked_symbols": ["POND/IDR"],
        "locked_sources": {"active_trades": 1},
        "open_sources": {},
        "errors": [],
    })

    governor = CapitalGovernor(None, None)
    governor.pending_daily_reset = True
    governor.current_total_equity_idr = 123_456.0
    await governor.check_daily_reset(governor.current_total_equity_idr)
    data = json.loads((tmp_path / "capital_governor.json").read_text(encoding="utf-8"))

    assert data["daily_reset_pending"] is False
    assert data["allow_new_orders"] is True
    assert data["locked_inventory_count"] == 1
    assert data["locked_inventory_symbols"] == ["POND/IDR"]
    assert data["date"] == str(today)


def test_load_daily_inventory_snapshot_dedupes_same_symbol(monkeypatch, tmp_path):
    _isolate_runtime_state(monkeypatch, tmp_path)
    _write_json(tmp_path / "active_trades.json", {
        "PHA/IDR": {
            "amount": 65.0,
            "price": 959.0,
            "exit_pending_order_id": "SELL-1",
        }
    })
    _write_json(tmp_path / "positions.json", {
        "open_positions": [
            {"symbol": "PHA/IDR", "amount": 65.0, "price": 959.0},
        ]
    })

    snapshot = capital_module.load_daily_inventory_snapshot(tmp_path)

    assert snapshot["has_open_inventory"] is True
    assert snapshot["open_count"] == 1
    assert snapshot["open_symbols"] == ["PHA/IDR"]
