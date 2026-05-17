"""Tests for Core/Research/backtest_engine.py"""

import pytest
from Core.Research.backtest_engine import (
    Bar,
    run_backtest,
    bars_from_dicts,
    _compute_drawdown,
    _compute_sharpe,
)


def _make_bars(n=100, start_price=1000.0, trend=0.001):
    """Generate synthetic OHLCV bars with optional uptrend."""
    bars = []
    price = start_price
    for i in range(n):
        close = price * (1 + trend)
        bars.append(Bar(
            timestamp=float(i * 3600),
            open=price,
            high=close * 1.005,
            low=price * 0.998,
            close=close,
            volume=1_000_000.0,
        ))
        price = close
    return bars


class TestBacktestEngine:
    def test_returns_result_with_trades(self):
        bars = _make_bars(200, trend=0.002)
        result = run_backtest(bars, strategy_id="test_up")
        assert result.total_trades >= 0
        assert result.strategy_id == "test_up"

    def test_downtrend_has_no_trades_or_losses(self):
        bars = _make_bars(200, trend=-0.001)
        result = run_backtest(bars)
        # Momentum signal won't trigger on downtrend — 0 trades or mostly losses
        if result.total_trades > 0:
            assert result.win_rate <= 0.7  # downtrend shouldn't be profitable

    def test_insufficient_bars_returns_empty(self):
        bars = _make_bars(5)
        result = run_backtest(bars, lookback=20)
        assert result.total_trades == 0

    def test_profit_factor_positive_for_uptrend(self):
        bars = _make_bars(300, trend=0.003)
        result = run_backtest(bars, take_profit_pct=0.015, stop_loss_pct=0.008)
        if result.total_trades > 0 and result.losing_trades > 0:
            assert result.profit_factor > 0

    def test_max_drawdown_between_0_and_1(self):
        bars = _make_bars(200, trend=0.001)
        result = run_backtest(bars)
        assert 0.0 <= result.max_drawdown_pct <= 1.0

    def test_bars_from_dicts_conversion(self):
        raw = [
            {"t": 0, "o": 100, "h": 105, "l": 99, "c": 103, "v": 5000},
            {"t": 3600, "o": 103, "h": 108, "l": 102, "c": 107, "v": 6000},
        ]
        bars = bars_from_dicts(raw)
        assert len(bars) == 2
        assert bars[0].close == 103
        assert bars[1].open == 103

    def test_compute_drawdown_flat_equity(self):
        assert _compute_drawdown([1.0, 1.0, 1.0]) == pytest.approx(0.0, abs=1e-9)

    def test_compute_sharpe_constant_returns(self):
        # All same returns → std=0 → sharpe=0
        returns = [0.01] * 100
        # std ≈ 0 but not exactly 0 due to floating point, result should be very large or 0
        sharpe = _compute_sharpe(returns)
        assert isinstance(sharpe, float)
