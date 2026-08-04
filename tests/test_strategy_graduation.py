"""Unit tests for Strategy Graduation and EV tracking pipeline."""

import json
from pathlib import Path
import pytest

from Core.Intelligence.strategy_stats import StrategyStatsAggregator, is_strategy_graduated


@pytest.fixture
def temp_stats_env(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    history_dir = state_dir / "trade_history"
    history_dir.mkdir(parents=True, exist_ok=True)

    import Core.Intelligence.strategy_stats as ss_mod
    monkeypatch.setattr(ss_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(ss_mod, "TRADE_HISTORY_DIR", history_dir)

    return state_dir, history_dir


def test_strategy_graduation_threshold_reached(temp_stats_env):
    state_dir, history_dir = temp_stats_env

    # Simulate 22 paper trades with 75% win rate and positive EV
    history_file = history_dir / "paper_2026-08-04.jsonl"
    lines = []
    for i in range(22):
        win = (i % 4 != 0)  # 75% win rate (16 wins, 6 losses)
        pnl = 2.5 if win else -1.0
        lines.append(json.dumps({
            "event_type": "ORDER_RECONCILED",
            "is_paper": True,
            "pair": "BTC_IDR",
            "strategy_id": "MOMENTUM_BOUNCE",
            "realized_pnl_pct": pnl,
            "state": "RECONCILED"
        }))
    history_file.write_text("\n".join(lines), encoding="utf-8")

    agg = StrategyStatsAggregator()
    agg.refresh_if_needed(force=True)

    graduated = agg.evaluate_and_update_graduations()
    assert "MOMENTUM_BOUNCE" in graduated
    assert graduated["MOMENTUM_BOUNCE"]["status"] == "GRADUATED_LIVE_READY"
    assert graduated["MOMENTUM_BOUNCE"]["sample_size"] == 22
    assert is_strategy_graduated("MOMENTUM_BOUNCE") is True


def test_strategy_quarantined_when_ev_negative(temp_stats_env):
    state_dir, history_dir = temp_stats_env

    # Simulate 12 paper trades with 10% win rate (negative EV)
    history_file = history_dir / "paper_2026-08-04.jsonl"
    lines = []
    for i in range(12):
        win = (i == 0)
        pnl = 1.0 if win else -3.0
        lines.append(json.dumps({
            "event_type": "ORDER_RECONCILED",
            "is_paper": True,
            "pair": "DOGE_IDR",
            "strategy_id": "BAD_STRAT",
            "realized_pnl_pct": pnl,
            "state": "RECONCILED"
        }))
    history_file.write_text("\n".join(lines), encoding="utf-8")

    agg = StrategyStatsAggregator()
    agg.refresh_if_needed(force=True)

    graduated = agg.evaluate_and_update_graduations()
    assert "BAD_STRAT" in graduated
    assert graduated["BAD_STRAT"]["status"] == "QUARANTINED"
    assert is_strategy_graduated("BAD_STRAT") is False
