"""Unit tests for Dynamic Trailing Stop Loss ratcheting in PaperTradeTracker."""

import json
from pathlib import Path
import pytest

from Core.Intelligence.paper_trade_tracker import PaperTradeTracker


@pytest.fixture
def temp_paper_env(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    open_dir = state_dir / "paper_trades" / "open"
    history_dir = state_dir / "trade_history"
    open_dir.mkdir(parents=True, exist_ok=True)
    history_dir.mkdir(parents=True, exist_ok=True)

    tracker = PaperTradeTracker(open_dir=open_dir, history_dir=history_dir)
    return tracker, open_dir


def test_trailing_stop_ratchets_up_with_profit(temp_paper_env):
    tracker, open_dir = temp_paper_env

    candidate = {
        "pair": "BTC_IDR",
        "symbol": "BTC/IDR",
        "price_idr": 100.0,
        "scorecard_verdict": "PAPER_ONLY",
    }

    # Open paper trade at entry_price 100.0, initial stop loss = 99.0 (-1%)
    trade = tracker.open_paper_trade(candidate, budget_idr=10000.0, stop_loss_pct=0.010, take_profit_pct=0.035)
    assert trade is not None
    initial_stop = trade["stop_loss_price"]
    assert initial_stop == 99.0

    # Simulate price ascending to 101.5 (+1.5% profit)
    # Schedule (1.2%, 0.6%) triggers -> new stop = 100 * (1 + 0.006) = 100.6
    closed = tracker.evaluate_open_trades({"BTC_IDR": 101.5})
    assert len(closed) == 0  # Should NOT close yet (neither SL nor TP hit)

    # Check that open position file has updated stop_loss_price to 100.6
    open_trades = tracker.get_open_paper_trades()
    assert len(open_trades) == 1
    updated_stop = open_trades[0]["stop_loss_price"]
    assert updated_stop > initial_stop
    assert abs(updated_stop - 100.6) < 0.01
