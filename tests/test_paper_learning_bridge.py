"""Unit test for Paper Trade -> Learning Engine & Quarantine Bridge."""

import json
from pathlib import Path
import pytest

from Core.Intelligence.paper_trade_tracker import PaperTradeTracker
from Core.Intelligence.kibot_learning_engine import get_engine
from Core.Intelligence.pair_quarantine import is_quarantined


@pytest.fixture
def temp_paper_bridge_env(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    open_dir = state_dir / "paper_trades" / "open"
    history_dir = state_dir / "trade_history"
    open_dir.mkdir(parents=True, exist_ok=True)
    history_dir.mkdir(parents=True, exist_ok=True)

    import Core.Intelligence.paper_trade_tracker as ptt_mod
    import Core.Intelligence.kibot_learning_engine as kle_mod
    import Core.Intelligence.pair_quarantine as pq_mod

    monkeypatch.setattr(ptt_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(ptt_mod, "PAPER_OPEN_DIR", open_dir)
    monkeypatch.setattr(ptt_mod, "TRADE_HISTORY_DIR", history_dir)

    monkeypatch.setattr(kle_mod, "STATE_ROOT", state_dir)
    monkeypatch.setattr(kle_mod, "STATE_PATH", state_dir / "learning_state.json")
    monkeypatch.setattr(kle_mod, "TRADE_LOG_FILE", state_dir / "trade_log.jsonl")

    monkeypatch.setattr(pq_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(pq_mod, "PAIR_FILE", state_dir / "pair_quarantine.json")

    tracker = PaperTradeTracker(open_dir=open_dir, history_dir=history_dir)
    return tracker, state_dir


def test_paper_trade_closing_feeds_learning_engine_and_quarantine(temp_paper_bridge_env):
    tracker, state_dir = temp_paper_bridge_env

    candidate = {
        "pair": "SOL_IDR",
        "symbol": "SOL/IDR",
        "price_idr": 1000.0,
        "scorecard_verdict": "PAPER_ONLY",
    }

    # Open paper trade
    trade = tracker.open_paper_trade(candidate, budget_idr=10000.0)
    assert trade is not None

    # Close with profit (+2.0%)
    closed = tracker.close_paper_trade(trade, exit_price=1020.0, exit_reason="TAKE_PROFIT_TARGET_HIT")
    assert closed["realized_pnl_idr"] > 0

    # Verify learning engine received record
    engine = get_engine()
    stats = engine.get_stats("sol_idr")
    assert stats.trade_count > 0
    assert stats.win_count > 0
