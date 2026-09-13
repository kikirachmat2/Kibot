import json
import pytest
from pathlib import Path
from unittest.mock import patch

from config import settings
from executor.virtual_ledger import VirtualLedger


def test_trade_pruning_sliding_window_and_archival(tmp_path):
    """
    Test generating 600 synthetic closed trades:
    - Verifies in-memory list is strictly capped at <= 500 (MAX_IN_MEMORY_TRADES).
    - Verifies the 100 oldest trades are accurately persisted to trades_archive.jsonl.
    """
    archive_file = tmp_path / "trades_archive.jsonl"
    
    with patch.object(settings, "STATE_DIR", tmp_path), patch.object(settings, "MAX_IN_MEMORY_TRADES", 500):
        ledger = VirtualLedger(initial_cash_idr=100_000_000.0)
        
        # Generate 600 closed trades
        for i in range(1, 601):
            buy_res = ledger.place_paper_buy(
                symbol=f"TEST{i}",
                price=1000.0,
                notional_idr=10_000.0,
            )
            assert buy_res["success"] is True
            # Immediately close position
            close_res = ledger.close_paper_position(
                symbol=f"TEST{i}",
                reason="TAKE_PROFIT" if i % 2 == 0 else "STOP_LOSS",
            )
            assert close_res is not None

        # 1. In-memory trade_history MUST be exactly 500
        assert len(ledger.trade_history) == 500
        
        # 2. In-memory should contain trades from #101 to #600
        assert ledger.trade_history[0]["symbol"] == "TEST101"
        assert ledger.trade_history[-1]["symbol"] == "TEST600"
        
        # 3. Archive file MUST exist and contain exactly 100 lines (trades #1 to #100)
        assert archive_file.exists()
        with open(archive_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
            
        assert len(lines) == 100
        first_archived = json.loads(lines[0])
        last_archived = json.loads(lines[-1])
        
        assert first_archived["symbol"] == "TEST1"
        assert last_archived["symbol"] == "TEST100"


def test_trade_pruning_failure_scenario_memory_still_pruned(tmp_path):
    """
    WHAT IF scenario: Disk full, permission denied, or archive write raises Exception.
    - Process MUST NOT crash.
    - In-memory trade_history MUST STILL be pruned to protect against process OOM.
    """
    with patch.object(settings, "STATE_DIR", tmp_path), patch.object(settings, "MAX_IN_MEMORY_TRADES", 500):
        ledger = VirtualLedger(initial_cash_idr=100_000_000.0)
        
        # Seed 500 trades
        for i in range(1, 501):
            ledger.trade_history.append({"symbol": f"COIN{i}", "closed_at": float(i)})
            
        assert len(ledger.trade_history) == 500
        
        # Mock file write to throw OSError (e.g. disk full / readonly filesystem)
        with patch("builtins.open", side_effect=OSError("No space left on device")):
            # Add 50 more trades
            for i in range(501, 551):
                ledger.trade_history.append({"symbol": f"COIN{i}", "closed_at": float(i)})
                ledger._prune_trade_history_if_needed()
                
        # Memory MUST still be bounded to 500, never leaking or growing unchecked
        assert len(ledger.trade_history) == 500
        assert ledger.trade_history[0]["symbol"] == "COIN51"
        assert ledger.trade_history[-1]["symbol"] == "COIN550"
