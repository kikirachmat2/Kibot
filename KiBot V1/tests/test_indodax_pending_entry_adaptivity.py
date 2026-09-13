#!/usr/bin/env python3
from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from Core.Executors.Indodax import indodax_executor as indodax_module
from Core.Executors.Indodax.indodax_executor import IndodaxExecutor


@pytest.mark.anyio
async def test_pending_entry_cancels_when_market_runs_away(monkeypatch):
    executor = IndodaxExecutor()
    executor._save_active_trades = lambda: None
    symbol = "EDEN/IDR"
    executor.active_trades[symbol] = {
        "amount": 0.0,
        "price": 1480.0,
        "entry_pending_order_id": "pending-001",
        "entry_pending_exchange_order_id": "EX-123",
        "entry_pending_price": 1480.0,
        "entry_pending_since": time.time() - 300,
        "entry_pending_status": "OPEN",
        "entry_pending_budget_idr": 10000.0,
    }

    executor.indodax.get_open_orders = AsyncMock(return_value={
        "orders": [{"order_id": "EX-123", "type": "buy"}]
    })
    executor.indodax.get_orderbook = AsyncMock(return_value={
        "bids": [["1569", "1"]],
        "asks": [["1570", "1"]],
    })
    executor.indodax.cancel_order = AsyncMock(return_value={"success": 1, "return": {"order_id": "EX-123"}})

    monkeypatch.setattr(indodax_module, "load_strategy", lambda: {
        "indodax": {
            "entry_pending_cancel_gap_pct": 2.0,
            "entry_pending_max_age_sec": 120,
        }
    })

    handled = await executor._handle_pending_entry(symbol, executor.active_trades[symbol])

    assert handled is True
    executor.indodax.cancel_order.assert_awaited_once()
    assert symbol not in executor.active_trades


@pytest.mark.anyio
async def test_pending_entry_keeps_waiting_when_market_is_close(monkeypatch):
    executor = IndodaxExecutor()
    executor._save_active_trades = lambda: None
    symbol = "EDEN/IDR"
    executor.active_trades[symbol] = {
        "amount": 0.0,
        "price": 1480.0,
        "entry_pending_order_id": "pending-001",
        "entry_pending_exchange_order_id": "EX-123",
        "entry_pending_price": 1480.0,
        "entry_pending_since": time.time() - 10,
        "entry_pending_status": "OPEN",
        "entry_pending_budget_idr": 10000.0,
    }

    executor.indodax.get_open_orders = AsyncMock(return_value={
        "orders": [{"order_id": "EX-123", "type": "buy"}]
    })
    executor.indodax.get_orderbook = AsyncMock(return_value={
        "bids": [["1480", "1"]],
        "asks": [["1481", "1"]],
    })
    executor.indodax.cancel_order = AsyncMock(return_value={"success": 1, "return": {"order_id": "EX-123"}})

    monkeypatch.setattr(indodax_module, "load_strategy", lambda: {
        "indodax": {
            "entry_pending_cancel_gap_pct": 2.0,
            "entry_pending_max_age_sec": 120,
        }
    })

    handled = await executor._handle_pending_entry(symbol, executor.active_trades[symbol])

    assert handled is True
    executor.indodax.cancel_order.assert_not_awaited()
    assert symbol in executor.active_trades
    assert executor.active_trades[symbol]["entry_pending_status"] == "OPEN"
