import time
from unittest.mock import AsyncMock

import pytest

from Core.Executors.Indodax import indodax_executor as indodax_module
from Core.Executors.Indodax.indodax_executor import IndodaxExecutor


@pytest.mark.anyio
async def test_pending_exit_reprices_stale_open_sell(monkeypatch):
    executor = IndodaxExecutor()
    executor._save_active_trades = lambda: None
    symbol = "PHA/IDR"
    executor.active_trades[symbol] = {
        "amount": 65.0,
        "price": 959.0,
        "cost": 62335.0,
        "exit_pending_order_id": "SELL-1",
        "exit_pending_amount": 65.0,
        "exit_pending_price": 959.0,
        "exit_pending_reason": "MIDNIGHT_DEADLINE",
        "exit_pending_fraction": 1.0,
        "exit_pending_since": time.time() - 300,
    }

    executor.indodax.get_open_orders = AsyncMock(return_value={
        "orders": [{"order_id": "SELL-1", "type": "sell"}]
    })
    executor.indodax.get_balance = AsyncMock(return_value=65.0)
    executor.indodax.get_orderbook = AsyncMock(return_value={
        "bids": [["947", "10"]],
        "asks": [["959", "10"]],
    })
    executor.indodax.cancel_order = AsyncMock(return_value={"success": 1})
    executor.execute_exit = AsyncMock()

    monkeypatch.setattr(indodax_module, "load_strategy", lambda: {
        "indodax": {
            "exit_pending_max_age_sec": 90,
            "exit_pending_reprice_gap_pct": 0.5,
            "fee_roundtrip_pct": 1.02,
        }
    })

    handled = await executor._handle_pending_exit(symbol, executor.active_trades[symbol])

    assert handled is True
    executor.indodax.cancel_order.assert_awaited_once_with(symbol, "SELL-1", "sell")
    executor.execute_exit.assert_awaited_once()
    args = executor.execute_exit.await_args.args
    assert args[0] == symbol
    assert args[1] == 947.0
    assert args[2] == "MIDNIGHT_DEADLINE"


@pytest.mark.anyio
async def test_pending_exit_keeps_fresh_open_sell(monkeypatch):
    executor = IndodaxExecutor()
    executor._save_active_trades = lambda: None
    symbol = "PHA/IDR"
    executor.active_trades[symbol] = {
        "amount": 65.0,
        "price": 959.0,
        "cost": 62335.0,
        "exit_pending_order_id": "SELL-1",
        "exit_pending_amount": 65.0,
        "exit_pending_price": 947.0,
        "exit_pending_reason": "MIDNIGHT_DEADLINE",
        "exit_pending_fraction": 1.0,
        "exit_pending_since": time.time() - 5,
    }

    executor.indodax.get_open_orders = AsyncMock(return_value={
        "orders": [{"order_id": "SELL-1", "type": "sell"}]
    })
    executor.indodax.get_balance = AsyncMock(return_value=65.0)
    executor.indodax.get_orderbook = AsyncMock(return_value={
        "bids": [["947", "10"]],
        "asks": [["959", "10"]],
    })
    executor.indodax.cancel_order = AsyncMock(return_value={"success": 1})

    monkeypatch.setattr(indodax_module, "load_strategy", lambda: {
        "indodax": {
            "exit_pending_max_age_sec": 90,
            "exit_pending_reprice_gap_pct": 0.5,
            "fee_roundtrip_pct": 1.02,
        }
    })

    handled = await executor._handle_pending_exit(symbol, executor.active_trades[symbol])

    assert handled is True
    executor.indodax.cancel_order.assert_not_awaited()
    assert executor.active_trades[symbol]["exit_blocked_reason"] == "EXIT_ORDER_OPEN:SELL-1"


@pytest.mark.anyio
async def test_hard_stop_detail_bypasses_profitable_floor(monkeypatch):
    executor = IndodaxExecutor()
    executor._save_active_trades = lambda: None
    symbol = "POND/IDR"
    executor.active_trades[symbol] = {
        "amount": 556.0,
        "price": 112.5,
        "cost": 62550.0,
    }

    executor.indodax.get_balance = AsyncMock(return_value=556.0)
    executor.indodax.get_pair_info = AsyncMock(return_value={
        "trade_min_traded_currency": 85,
        "trade_min_base_currency": 10000,
    })
    executor.indodax.trade = AsyncMock(return_value={"success": 1, "return": {"order_id": "SELL-2"}})
    executor.indodax.get_open_orders = AsyncMock(return_value={"orders": [{"order_id": "SELL-2", "type": "sell"}]})

    monkeypatch.setattr(indodax_module, "load_strategy", lambda: {
        "indodax": {
            "fee_roundtrip_pct": 1.02,
            "exit_profit_buffer_pct": 0.3,
        }
    })

    await executor.execute_exit(symbol, 108.0, "HARD_STOP (-4.00% < -2.5%)")

    executor.indodax.trade.assert_awaited_once()
    assert executor.indodax.trade.await_args.kwargs["price"] == 108.0
    assert executor.active_trades[symbol]["exit_pending_order_id"] == "SELL-2"
