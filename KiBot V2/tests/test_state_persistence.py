import tempfile
from pathlib import Path
import pytest

from executor.virtual_ledger import VirtualLedger, VirtualPosition
from paper_trade_runner import PaperTradeRunner
from storage import durable_state_store

def test_virtual_ledger_restore_zero_cash():
    """Verify that a ledger holding 0 cash (100% invested) restores 0 cash and exact equity."""
    ledger = VirtualLedger(initial_cash_idr=100_000.0, name="TEST_ZERO")
    ledger.cash_idr = 0.0
    pos = VirtualPosition(
        position_id="test_pos_1",
        symbol="BTCIDR",
        side="BUY",
        entry_price=1000.0,
        current_price=1000.0,
        amount_coins=100.0,
        cost_idr=100_000.0,
        initial_cost_idr=100_000.0,
        entry_time=1.0,
        stop_loss_price=900.0,
        take_profit_price=1100.0,
        max_price_seen=1000.0,
        max_hold_time_s=1000.0,
        strategy="TEST",
    )
    ledger.open_positions["BTCIDR"] = pos
    
    eq_before = ledger.get_total_equity()
    assert eq_before == 100_000.0
    assert ledger.cash_idr == 0.0

    # Simulate restart with new ledger instance
    ledger2 = VirtualLedger(initial_cash_idr=100_000.0, name="TEST_ZERO")
    ledger2.restore_state(
        cash_idr=0.0,
        open_positions_data={"BTCIDR": pos.to_dict()},
        trade_history_data=[],
    )

    assert ledger2.cash_idr == 0.0
    assert ledger2.get_total_equity() == 100_000.0
    assert len(ledger2.open_positions) == 1
    assert "BTCIDR" in ledger2.open_positions

def test_paper_trade_runner_full_persistence(tmp_path):
    """Verify save -> restore roundtrip for all metrics: equity, positions, trades, week_start_equity."""
    state_file = tmp_path / "paper_state.json"
    runner = PaperTradeRunner(state_file=state_file)

    # Place trades on P1 and P2
    p1 = runner.ledgers["P1"]
    res1 = p1.place_paper_buy("BTCIDR", 1000.0, 50_000.0)
    assert res1["success"]

    res2 = p1.place_paper_buy("ETHIDR", 1000.0, 50_000.0)
    assert res2["success"]
    assert p1.cash_idr == 0.0

    # Simulate a closed trade on P3
    p3 = runner.ledgers["P3"]
    p3.place_paper_buy("SOLIDR", 1000.0, 20_000.0)
    p3.close_paper_position("SOLIDR", reason="TAKE_PROFIT")
    assert len(p3.trade_history) == 1

    runner.week_start_equity["P1"] = 100_000.0
    runner.week_start_equity["P3"] = 100_000.0

    p1_eq_expected = p1.get_total_equity()
    p1_cash_expected = p1.cash_idr
    p3_eq_expected = p3.get_total_equity()
    p3_trades_count = len(p3.trade_history)

    # Save state
    runner._save_state()

    # Re-hydrate from file
    runner2 = PaperTradeRunner(state_file=state_file)
    p1_restored = runner2.ledgers["P1"]
    p3_restored = runner2.ledgers["P3"]

    # 1. Equity identik
    assert abs(p1_restored.get_total_equity() - p1_eq_expected) < 0.01
    assert abs(p3_restored.get_total_equity() - p3_eq_expected) < 0.01

    # 2. Cash identik (including 0.0 cash)
    assert abs(p1_restored.cash_idr - p1_cash_expected) < 0.01
    assert p1_restored.cash_idr == 0.0

    # 3. Positions identik
    assert set(p1_restored.open_positions.keys()) == {"BTCIDR", "ETHIDR"}
    assert len(p3_restored.open_positions) == 0

    # 4. Closed trades identik
    assert len(p3_restored.trade_history) == p3_trades_count
    assert p3_restored.trade_history[0]["symbol"] == "SOLIDR"

    # 5. week_start_equity identik
    assert runner2.week_start_equity["P1"] == 100_000.0
    assert runner2.week_start_equity["P3"] == 100_000.0

def test_paper_variants_do_not_pollute_durable_state_store(tmp_path):
    """Ensure non-core paper variants (P1-P5) never pollute durable_state.json."""
    initial_snap = dict(durable_state_store.get_state())

    runner = PaperTradeRunner(state_file=tmp_path / "paper_isolated.json")
    runner.ledgers["P1"].place_paper_buy("BTCIDR", 1000.0, 50_000.0)

    final_snap = dict(durable_state_store.get_state())
    assert initial_snap == final_snap
