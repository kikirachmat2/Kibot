"""
Unit tests for Choppiness Index (CI), Volume Z-Score, and Bollinger %B.
Validates pure mathematical correctness against canonical quantitative definitions.
"""
import pytest
from council.indicators import (
    calc_choppiness_index,
    calc_volume_zscore,
    calc_bollinger_pct_b,
    calc_bollinger_bands,
)

def test_choppiness_index_trending_vs_choppy():
    """Verify Choppiness Index is low during clean trends and high during choppy whipsaws."""
    # 1. Clean directional linear trend (Highs and Lows expanding steadily upwards)
    n = 30
    trend_highs = [100.0 + i * 2.0 + 1.0 for i in range(n)]
    trend_lows = [100.0 + i * 2.0 - 0.5 for i in range(n)]
    trend_closes = [100.0 + i * 2.0 for i in range(n)]

    ci_trend = calc_choppiness_index(trend_highs, trend_lows, trend_closes, period=14)
    assert len(ci_trend) == n
    # During strong directional linear expansion, CI should be low (< 45)
    assert ci_trend[-1] < 45.0

    # 2. Extreme choppy whipsaw (oscillating within fixed narrow bracket, high total TR, small net range)
    chop_highs = [100.0 + (5.0 if i % 2 == 0 else -1.0) for i in range(n)]
    chop_lows = [100.0 + (-5.0 if i % 2 == 0 else 1.0) for i in range(n)]
    chop_closes = [100.0 + (4.0 if i % 2 == 0 else -4.0) for i in range(n)]

    ci_chop = calc_choppiness_index(chop_highs, chop_lows, chop_closes, period=14)
    assert len(ci_chop) == n
    # In oscillating chop, sum(TR) is high relative to (MaxH - MinL), so CI > 60.0
    assert ci_chop[-1] > 60.0

def test_volume_zscore():
    """Verify Volume Z-score detects anomalous volume expansions."""
    # 20 bars of baseline volume around 100, then an explosive spike of 500
    volumes = [100.0] * 20 + [500.0]
    z_scores = calc_volume_zscore(volumes, period=20)
    assert len(z_scores) == len(volumes)
    # The spike at index 20 should have a strongly positive Z-score (> 3.0)
    assert z_scores[-1] > 3.0

def test_bollinger_pct_b():
    """Verify Bollinger %B accurately reflects position relative to bands."""
    closes = [10.0, 20.0, 30.0]
    upper = [20.0, 25.0, 28.0]
    lower = [10.0, 15.0, 20.0]

    pct_b = calc_bollinger_pct_b(closes, upper, lower)
    # At index 0: close = 10, lower = 10 -> %B = 0.0
    assert pct_b[0] == pytest.approx(0.0)
    # At index 1: close = 20, lower = 15, upper = 25 -> %B = 0.5
    assert pct_b[1] == pytest.approx(0.5)
    # At index 2: close = 30, lower = 20, upper = 28 -> %B = 1.25 (overshot upper band)
    assert pct_b[2] == pytest.approx(1.25)
