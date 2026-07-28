"""Tests for Core/Intelligence/strategy_stats.py and EV pipeline integration."""

import json
from pathlib import Path
import pytest

from Core.Intelligence.strategy_stats import StrategyStatsAggregator, StrategyMetrics
from Core.Intelligence.expected_value import ev_from_candidate
from Core.Intelligence.autonomous_director import AutonomousDirector


@pytest.fixture
def temp_history_dir(tmp_path, monkeypatch):
    import Core.Intelligence.strategy_stats as ss_mod

    state_dir = tmp_path / "state"
    history_dir = state_dir / "trade_history"
    orders_dir = state_dir / "orders"
    history_dir.mkdir(parents=True, exist_ok=True)
    orders_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(ss_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(ss_mod, "TRADE_HISTORY_DIR", history_dir)
    monkeypatch.setattr(ss_mod, "ORDERS_DIR", orders_dir)

    return history_dir, orders_dir


def test_strategy_stats_aggregation(temp_history_dir):
    history_dir, _ = temp_history_dir

    # Write 25 sample trades for EDENA/IDR (18 wins, 7 losses)
    lines = []
    for i in range(18):
        lines.append(json.dumps({
            "state": "RECONCILED",
            "pair": "EDENA/IDR",
            "strategy_id": "MOMENTUM",
            "realized_pnl_pct": 3.0,  # 3% profit
        }))
    for i in range(7):
        lines.append(json.dumps({
            "state": "RECONCILED",
            "pair": "EDENA/IDR",
            "strategy_id": "MOMENTUM",
            "realized_pnl_pct": -1.0,  # 1% loss
        }))

    (history_dir / "2026-05-27.jsonl").write_text("\n".join(lines), encoding="utf-8")

    aggregator = StrategyStatsAggregator(ttl_seconds=0)
    aggregator.refresh_if_needed(force=True)

    cand = {"strategy_id": "MOMENTUM", "pair": "EDENA/IDR"}
    aggregator.inject_stats(cand)

    assert cand["historical_sample_size"] == 25
    assert round(cand["win_rate"], 2) == 0.72  # 18/25
    assert round(cand["avg_profit_pct"], 3) == 0.03
    assert round(cand["avg_loss_pct"], 3) == 0.01


def test_ev_gating_verdicts():
    # 1. Sample >= 20 + EV bagus -> approved = True
    good_cand = {
        "historical_sample_size": 25,
        "win_rate": 0.65,
        "avg_profit_pct": 0.03,
        "avg_loss_pct": 0.01,
        "signal_quality": {"grade": "STRONG"},
    }
    ev_good = ev_from_candidate(good_cand)
    assert ev_good.approved is True

    # 2. Sample < 20 -> approved = False in EVResult, but verdict is PAPER_ONLY in director
    low_sample_cand = {
        "historical_sample_size": 5,
        "win_rate": 0.70,
        "avg_profit_pct": 0.04,
        "avg_loss_pct": 0.01,
        "signal_quality": {"grade": "STRONG", "score": 0.85},
        "strategy_id": "NEW_STRAT",
    }
    ev_low = ev_from_candidate(low_sample_cand)
    assert ev_low.approved is False
    assert "below minimum 20" in ev_low.rejection_reasons[0]

    director = AutonomousDirector(market_regime="BULL")
    res = director.evaluate_cycle([low_sample_cand], market_regime="BULL")
    assert len(res["shadow"]) == 1  # Placed in shadow / PAPER_ONLY
    assert len(res["approved"]) == 0
    assert res["shadow"][0]["scorecard_verdict"] == "PAPER_ONLY"

    # 3. Sample >= 20 tapi EV jelek -> approved = False, REJECTED verdict
    bad_ev_cand = {
        "historical_sample_size": 30,
        "win_rate": 0.30,  # 30% win rate
        "avg_profit_pct": 0.01,
        "avg_loss_pct": 0.03,
        "signal_quality": {"grade": "MARGINAL", "score": 0.4},
        "strategy_id": "BAD_STRAT",
    }
    ev_bad = ev_from_candidate(bad_ev_cand)
    assert ev_bad.approved is False

    res_bad = director.evaluate_cycle([bad_ev_cand], market_regime="BEAR")
    assert len(res_bad["rejected"]) == 1
    assert res_bad["rejected"][0]["scorecard_verdict"] == "REJECTED"
