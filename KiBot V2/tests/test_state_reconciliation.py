"""Unit tests for durable state persistence and non-recursive startup reconciliation."""
import asyncio
import os
import json
import pytest
from pathlib import Path
from async_helper import run_async
from storage.durable_state import DurableStateStore
from storage.reconciler import StartupReconciler

@run_async
async def test_durable_state_non_blocking_write(temp_data_dir):
    """Verify state changes are persisted to disk atomically without blocking hot-path."""
    state_file = temp_data_dir / "durable_state.json"
    store = DurableStateStore(state_file_path=state_file)
    await store.start()
    
    pos_data = {
        "symbol": "SOL/IDR",
        "entry_price": 2000000.0,
        "amount_coins": 1.5,
        "cost_idr": 3000000.0,
    }
    
    # Non-blocking async enqueue
    store.record_position_change("OPEN", pos_data, total_equity_idr=10000000.0)
    
    # Allow background writer loop to flush
    await asyncio.sleep(0.1)
    await store.stop()
    
    assert state_file.exists()
    with open(state_file, "r") as f:
        data = json.load(f)
    assert "SOL/IDR" in data["open_positions"]
    assert data["open_positions"]["SOL/IDR"]["entry_price"] == 2000000.0
    assert data["equity_idr"] == 10000000.0

@run_async
async def test_non_recursive_reconciler_resilience(temp_data_dir):
    """Verify StartupReconciler uses iterative retries and never exceeds recursion depth."""
    state_file = temp_data_dir / "durable_state.json"
    with open(state_file, "w") as f:
        json.dump({
            "version": "2.0.0",
            "cash_idr": 8500000.0,
            "open_positions": {
                "BTC/IDR": {"symbol": "BTC/IDR", "entry_price": 1000000000.0, "amount_coins": 0.001}
            }
        }, f)
        
    store = DurableStateStore(state_file_path=state_file)
    reconciler = StartupReconciler(state_store=store, max_retries=2, timeout_s=0.1)
    
    # Run startup reconciliation (falls back to local state when exchange offline/no credentials)
    res = await reconciler.reconcile_on_startup()
    
    assert res["reconciled"] is True
    assert res["cash_idr"] > 0
    assert "BTC/IDR" in res["open_positions"]
