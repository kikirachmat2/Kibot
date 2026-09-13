"""Tests for Core/Research/walk_forward.py"""

import pytest
from Core.Research.backtest_engine import Bar, bars_from_dicts
from Core.Research.walk_forward import (
    run_walk_forward,
    MIN_OOS_WIN_RATE,
    MIN_EFFICIENCY_RATIO,
)


def _make_bars(n=500, trend=0.001):
    bars = []
    price = 1000.0
    for i in range(n):
        close = price * (1 + trend)
        bars.append(Bar(
            timestamp=float(i * 3600),
            open=price,
            high=close * 1.006,
            low=price * 0.997,
            close=close,
            volume=2_000_000.0,
        ))
        price = close
    return bars


class TestWalkForward:
    def test_insufficient_bars_returns_rejection(self):
        bars = _make_bars(5)
        result = run_walk_forward(bars, lookback=20)
        assert result.viable is False
        assert len(result.rejection_reasons) > 0

    def test_produces_n_folds_on_valid_data(self):
        bars = _make_bars(500, trend=0.002)
        result = run_walk_forward(bars, n_folds=4, lookback=20)
        assert result.n_folds <= 4
        assert result.n_folds >= 0

    def test_result_has_to_dict(self):
        bars = _make_bars(300, trend=0.002)
        result = run_walk_forward(bars, n_folds=3, lookback=20)
        d = result.to_dict()
        assert "viable" in d
        assert "oos_expectancy_pct" in d
        assert "efficiency_ratio" in d
        assert "fold_summary" in d

    def test_efficiency_ratio_finite(self):
        bars = _make_bars(500, trend=0.003)
        result = run_walk_forward(bars, n_folds=3, lookback=20)
        assert isinstance(result.efficiency_ratio, float)
        assert result.efficiency_ratio != float("inf")

    def test_custom_signal_fn_accepted(self):
        bars = _make_bars(300, trend=0.002)

        def always_buy(bar, hist):
            return True  # enter every bar

        result = run_walk_forward(
            bars, n_folds=3, lookback=20, entry_signal_fn=always_buy
        )
        assert isinstance(result.viable, bool)

    def test_oos_fields_non_negative(self):
        bars = _make_bars(500, trend=0.002)
        result = run_walk_forward(bars, n_folds=4, lookback=20)
        assert result.oos_win_rate >= 0.0
        assert result.oos_max_drawdown_pct >= 0.0
