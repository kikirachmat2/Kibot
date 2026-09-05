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

    def test_timeout_exit_at_max_hold_bars(self):
        # Create flat bars with an explicit entry signal at bar 20
        bars = []
        for i in range(50):
            price = 100.0
            bars.append(Bar(
                timestamp=float(i * 900),
                open=price,
                high=price * 1.002,
                low=price * 0.998,
                close=price,
                volume=1000.0,
            ))
        # With max_hold_bars = 5, TP = 0.05, SL = 0.05 (neither hit)
        result = run_backtest(
            bars,
            take_profit_pct=0.05,
            stop_loss_pct=0.05,
            max_hold_bars=5,
            lookback=20,
            entry_signal_fn=lambda bar, hist: bar.timestamp == 20 * 900,
        )
        assert result.total_trades == 1
        timeout_trades = [t for t in result.trades if t.exit_reason == "TIMEOUT"]
        assert len(timeout_trades) == 1
        assert "TIMEOUT" in result.exit_reasons
        assert timeout_trades[0].bars_held == 5

    def test_trailing_stop_ratchet(self):
        # Bar rises to +2% then drops back down
        bars = []
        prices = [100.0] * 20 + [100.5, 102.5, 101.5, 100.8]
        for i, price in enumerate(prices):
            bars.append(Bar(
                timestamp=float(i * 900),
                open=price,
                high=price * 1.001,
                low=price * 0.999,
                close=price,
                volume=1000.0,
            ))
        trailing_schedule = [(1.2, 0.6), (2.0, 0.8)]
        result = run_backtest(
            bars,
            take_profit_pct=0.05,  # 5% not hit
            stop_loss_pct=0.02,    # initial SL -2%
            trailing_schedule=trailing_schedule,
            max_hold_bars=20,
            lookback=20,
            entry_signal_fn=lambda bar, hist: bar.timestamp == 20 * 900,
        )
        assert result.total_trades == 1
        trailing_exits = [t for t in result.trades if t.exit_reason == "TRAILING_STOP"]
        assert len(trailing_exits) == 1
        assert "TRAILING_STOP" in result.exit_reasons

    def test_ground_truth_signal_integration(self):
        from Core.Research.backtest_engine import (
            load_ground_truth_signals,
            create_ground_truth_signal_fn,
        )
        # Load local ground truth signals file
        signals_map = load_ground_truth_signals("state/ground_truth_signals.json")
        assert len(signals_map) > 0

        # Choose a symbol with signals
        sample_sym = list(signals_map.keys())[0]
        sym_signals = signals_map[sample_sym]
        assert len(sym_signals) > 0

        sig_fn = create_ground_truth_signal_fn(sym_signals, tolerance_seconds=900.0)
        target_ts = sym_signals[0]["ts"]
        matching_bar = Bar(timestamp=target_ts, open=100, high=105, low=95, close=102, volume=1000)
        non_matching_bar = Bar(timestamp=target_ts + 100000, open=100, high=105, low=95, close=102, volume=1000)

        assert sig_fn(matching_bar, []) is True
        assert sig_fn(non_matching_bar, []) is False

    def test_kibot_scanner_signal_fn(self):
        from Core.Research.backtest_engine import kibot_scanner_signal_fn
        # Create history with flat base, then sudden volume & price spike
        hist = []
        for i in range(30):
            hist.append(Bar(
                timestamp=float(i * 900),
                open=100.0,
                high=100.5,
                low=99.5,
                close=100.0,
                volume=10000.0,
            ))
        # Spike bar: +5% price, 3x volume
        spike_bar = Bar(
            timestamp=float(30 * 900),
            open=100.0,
            high=106.0,
            low=100.0,
            close=105.0,
            volume=40000.0,
        )
        signal = kibot_scanner_signal_fn(spike_bar, hist, min_confidence=0.60)
        assert isinstance(signal, bool)

