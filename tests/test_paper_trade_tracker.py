"""Unit tests for PaperTradeTracker and full end-to-end integration with StrategyStats Aggregator."""

import json
import time
from pathlib import Path
import pytest

from Core.Intelligence.paper_trade_tracker import PaperTradeTracker
from Core.Intelligence.strategy_stats import StrategyStatsAggregator
from Core.Intelligence.autonomous_director import AutonomousDirector


@pytest.fixture
def temp_paper_env(tmp_path, monkeypatch):
    import Core.Intelligence.paper_trade_tracker as ptt_mod
    import Core.Intelligence.strategy_stats as ss_mod

    state_dir = tmp_path / "state"
    open_dir = state_dir / "paper_trades" / "open"
    history_dir = state_dir / "trade_history"
    orders_dir = state_dir / "orders"

    open_dir.mkdir(parents=True, exist_ok=True)
    history_dir.mkdir(parents=True, exist_ok=True)
    orders_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(ptt_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(ptt_mod, "PAPER_OPEN_DIR", open_dir)
    monkeypatch.setattr(ptt_mod, "TRADE_HISTORY_DIR", history_dir)

    monkeypatch.setattr(ss_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(ss_mod, "TRADE_HISTORY_DIR", history_dir)
    monkeypatch.setattr(ss_mod, "ORDERS_DIR", orders_dir)

    tracker = PaperTradeTracker(open_dir=open_dir, history_dir=history_dir)
    aggregator = StrategyStatsAggregator(ttl_seconds=0)

    return tracker, aggregator, history_dir, open_dir


def test_full_paper_trade_lifecycle(temp_paper_env):
    tracker, aggregator, history_dir, open_dir = temp_paper_env

    # 1. Candidate gets PAPER_ONLY verdict
    shadow_candidate = {
        "symbol": "MOCK/IDR",
        "pair": "MOCK/IDR",
        "strategy_id": "MOMENTUM_TEST",
        "price_idr": 100.0,
        "scorecard_verdict": "PAPER_ONLY",
    }

    # 2. Open paper trade with calibrated TP=+3.0% / SL=-1.0%
    opened = tracker.open_paper_trade(shadow_candidate, budget_idr=10000.0, stop_loss_pct=0.010, take_profit_pct=0.030)
    assert opened is not None
    assert opened["pair"] == "MOCK/IDR"
    assert opened["entry_price_idr"] == 100.0
    assert len(tracker.get_open_paper_trades()) == 1

    # 3. Simulate market price move -> hits Take Profit target at 103.0 IDR (+3%)
    price_map = {"MOCK/IDR": 103.0}
    closed_list = tracker.evaluate_open_trades(price_map)

    assert len(closed_list) == 1
    closed = closed_list[0]
    assert closed["pair"] == "MOCK/IDR"
    assert closed["exit_reason"] == "TAKE_PROFIT_TARGET_HIT"
    assert closed["is_paper"] is True
    assert closed["realized_pnl_pct"] > 0.0  # Net profit after fee

    # Verify open trade file removed
    assert len(tracker.get_open_paper_trades()) == 0

    # 4. Verify paper trade history file written
    paper_files = list(history_dir.glob("paper_*.jsonl"))
    assert len(paper_files) == 1
    content = paper_files[0].read_text(encoding="utf-8")
    assert "MOCK/IDR" in content
    assert '"is_paper": true' in content.lower()

    # 5. Verify StrategyStatsAggregator reads the paper trade and updates sample size
    aggregator.refresh_if_needed(force=True)
    metrics, is_specific = aggregator.get_metrics_for_candidate(shadow_candidate)

    assert is_specific is True
    assert metrics.total_trades == 1
    assert metrics.sample_size_paper == 1
    assert metrics.sample_size_live == 0
    assert metrics.win_rate == 1.0


def test_autonomous_director_paper_trading_pipeline(temp_paper_env, monkeypatch):
    tracker, aggregator, history_dir, open_dir = temp_paper_env
    import Core.Intelligence.paper_trade_tracker as ptt_mod
    monkeypatch.setattr(ptt_mod, "_tracker_instance", tracker)

    # Mock get_paper_trade_tracker inside director to use test tracker
    import Core.Intelligence.autonomous_director as ad_mod
    monkeypatch.setattr(ad_mod, "batch_evaluate_ev", lambda cands: cands)

    director = AutonomousDirector(market_regime="BULL")

    # Pass a shadow candidate
    cand = {
        "symbol": "SOL/IDR",
        "pair": "SOL/IDR",
        "price_idr": 1000.0,
        "spread_pct": 0.001,
        "volume_ratio": 1.5,
        "leadlag_score": 0.8,
        "daily_volatility_pct": 0.03,
        "data_age_seconds": 2.0,
        "strategy_id": "SOL_MOMENTUM",
        "is_specific_match": False,  # Will cause PAPER_ONLY cap
    }

    res = director.evaluate_cycle([cand], market_regime="BULL")
    assert len(res["shadow"]) == 1

    # Verify open paper trade created by director cycle
    open_trades = tracker.get_open_paper_trades()
    assert len(open_trades) == 1
    assert open_trades[0]["pair"] == "SOL/IDR"


def test_paper_trade_rr_ratio_safety_check(temp_paper_env):
    tracker, _, _, _ = temp_paper_env
    from Core.Intelligence.paper_trade_tracker import compute_net_rr_ratio, MIN_NET_RR_BUFFER

    # 1. Test default TP=+3.0% / SL=-1.0% net R:R ratio calculation
    default_net_rr = compute_net_rr_ratio(take_profit_pct=0.03, stop_loss_pct=0.01)
    assert default_net_rr >= MIN_NET_RR_BUFFER  # Must be >= 1.60 (actual: 1.857)

    cand = {"symbol": "TEST/IDR", "pair": "TEST/IDR", "price_idr": 100.0}

    # 2. Valid trade (TP=3%, SL=1%) opens successfully
    valid_trade = tracker.open_paper_trade(cand, take_profit_pct=0.03, stop_loss_pct=0.01)
    assert valid_trade is not None

    # 3. Invalid trade with bad R:R (TP=2%, SL=1.5% -> net RR ~0.84) must be blocked
    invalid_cand = {"symbol": "BAD/IDR", "pair": "BAD/IDR", "price_idr": 100.0}
    blocked_trade = tracker.open_paper_trade(invalid_cand, take_profit_pct=0.02, stop_loss_pct=0.015)
    assert blocked_trade is None
