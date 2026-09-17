"""
Technical Indicators for KiBot V2 Swing Strategy.
Pure mathematical implementations matching the 730-day Indodax backtest logic.
Zero external heavy dependencies (NumPy/Pandas free) for minimal memory footprint and fast execution.
"""
from __future__ import annotations

import math
from typing import List, Tuple, Dict, Any


def calc_ema(data: List[float], span: int) -> List[float]:
    """Calculates Exponential Moving Average (EMA) for a series."""
    if not data:
        return []
    alpha = 2.0 / (span + 1.0)
    ema = [data[0]]
    for p in data[1:]:
        ema.append(p * alpha + ema[-1] * (1.0 - alpha))
    return ema


def calc_sma(data: List[float], window: int) -> List[float]:
    """Calculates Simple Moving Average (SMA) for a series."""
    n = len(data)
    if n == 0 or window <= 0:
        return []
    sma = [0.0] * n
    for i in range(n):
        start_idx = max(0, i - window + 1)
        sub = data[start_idx : i + 1]
        sma[i] = sum(sub) / len(sub)
    return sma


def calc_rsi(closes: List[float], period: int = 14) -> List[float]:
    """
    Calculates Relative Strength Index (RSI) using Wilder's Smoothing.
    Matches standard TradingView / Wilder formula.
    """
    n = len(closes)
    if n == 0:
        return []
    rsi = [50.0] * n
    if n <= period:
        return rsi

    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains[i] = diff
        else:
            losses[i] = abs(diff)

    avg_gain = [0.0] * n
    avg_loss = [0.0] * n
    avg_gain[period] = sum(gains[1 : period + 1]) / float(period)
    avg_loss[period] = sum(losses[1 : period + 1]) / float(period)

    for i in range(period + 1, n):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i]) / float(period)
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i]) / float(period)
        if avg_loss[i] > 0:
            rs = avg_gain[i] / avg_loss[i]
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))
        else:
            rsi[i] = 100.0 if avg_gain[i] > 0 else 50.0

    return rsi


def calc_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
    """Calculates Average True Range (ATR) with Wilder's smoothing."""
    n = len(closes)
    if n == 0:
        return []
    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))

    atr = [tr[0]] * n
    for i in range(1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / float(period)
    return atr


def calc_bollinger_bands(
    closes: List[float], period: int = 20, num_std: float = 2.0
) -> Tuple[List[float], List[float], List[float]]:
    """
    Calculates Bollinger Bands (Middle/SMA, Upper, Lower).
    Returns (middle, upper, lower).
    """
    n = len(closes)
    if n == 0:
        return [], [], []
    middle = [0.0] * n
    upper = [0.0] * n
    lower = [0.0] * n

    for i in range(n):
        start_idx = max(0, i - period + 1)
        sub = closes[start_idx : i + 1]
        mean = sum(sub) / float(len(sub))
        var = sum((x - mean) ** 2 for x in sub) / float(len(sub))
        std = math.sqrt(var)
        middle[i] = mean
        upper[i] = mean + (num_std * std)
        lower[i] = mean - (num_std * std)

    return middle, upper, lower


def calc_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
    """
    Calculates Average Directional Index (ADX 14) using Wilder's smoothing.
    """
    n = len(closes)
    if n == 0:
        return []
    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))

    dm_plus = [0.0] * n
    dm_minus = [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        if up > down and up > 0:
            dm_plus[i] = up
        if down > up and down > 0:
            dm_minus[i] = down

    smooth_dm_plus = [0.0] * n
    smooth_dm_minus = [0.0] * n
    smooth_tr = [0.0] * n
    adx = [20.0] * n
    dx = [0.0] * n

    if n > (period * 2):
        smooth_dm_plus[period] = sum(dm_plus[1 : period + 1])
        smooth_dm_minus[period] = sum(dm_minus[1 : period + 1])
        smooth_tr[period] = sum(tr[1 : period + 1])

        for i in range(period + 1, n):
            smooth_dm_plus[i] = smooth_dm_plus[i - 1] - (smooth_dm_plus[i - 1] / float(period)) + dm_plus[i]
            smooth_dm_minus[i] = smooth_dm_minus[i - 1] - (smooth_dm_minus[i - 1] / float(period)) + dm_minus[i]
            smooth_tr[i] = smooth_tr[i - 1] - (smooth_tr[i - 1] / float(period)) + tr[i]

            di_plus = 100.0 * (smooth_dm_plus[i] / smooth_tr[i]) if smooth_tr[i] > 0 else 0.0
            di_minus = 100.0 * (smooth_dm_minus[i] / smooth_tr[i]) if smooth_tr[i] > 0 else 0.0
            di_sum = di_plus + di_minus
            dx[i] = 100.0 * (abs(di_plus - di_minus) / di_sum) if di_sum > 0 else 0.0

        adx[period * 2] = sum(dx[period + 1 : (period * 2) + 1]) / float(period)
        for i in range((period * 2) + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / float(period)

    return adx


def calc_slope(series: List[float], lookback: int = 5) -> float:
    """
    Calculates percentage slope over lookback period: (series[-1] - series[-1-lookback]) / series[-1-lookback].
    Returns fractional change (e.g. 0.02 = 2.0%).
    """
    if len(series) <= lookback:
        return 0.0
    ref = series[-1 - lookback]
    if ref == 0:
        return 0.0
    return (series[-1] - ref) / ref


def calc_choppiness_index(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
    """
    Calculates Choppiness Index (CI) for trend vs range differentiation.
    Formula: 100 * LOG10( SUM(TrueRange(1), n) / (MaxHigh(n) - MinLow(n)) ) / LOG10(n)
    CI > 61.8 indicates consolidation / chop (whipsaw danger).
    CI < 38.2 indicates strong directional trend.
    """
    n = len(closes)
    if n == 0:
        return []
    ci = [50.0] * n
    if n <= period:
        return ci

    # 1-period True Range for each bar
    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))

    log10_period = math.log10(float(period))

    for i in range(period, n):
        sum_tr = sum(tr[i - period + 1 : i + 1])
        max_h = max(highs[i - period + 1 : i + 1])
        min_l = min(lows[i - period + 1 : i + 1])
        rng = max_h - min_l
        if rng > 0 and sum_tr > 0:
            val = 100.0 * (math.log10(sum_tr / rng) / log10_period)
            ci[i] = max(0.0, min(100.0, val))
        else:
            ci[i] = 50.0

    return ci


def calc_volume_zscore(volumes: List[float], period: int = 20) -> List[float]:
    """
    Calculates Volume Z-score: (Volume - Mean(Volume, period)) / Std(Volume, period).
    Positive Z-score indicates volume thrust / expansion above historical baseline.
    """
    n = len(volumes)
    if n == 0:
        return []
    z_scores = [0.0] * n
    if n < period:
        return z_scores

    for i in range(period - 1, n):
        window = volumes[i - period + 1 : i + 1]
        mean = sum(window) / float(period)
        variance = sum((x - mean) ** 2 for x in window) / float(period)
        std = math.sqrt(variance)
        if std > 0:
            z_scores[i] = (volumes[i] - mean) / std
        else:
            z_scores[i] = 0.0

    return z_scores


def calc_bollinger_pct_b(closes: List[float], upper: List[float], lower: List[float]) -> List[float]:
    """
    Calculates Bollinger %B: (Close - LowerBB) / (UpperBB - LowerBB).
    %B <= 0.0 indicates price below lower band (deep oversold).
    %B >= 1.0 indicates price above upper band (deep overbought).
    """
    n = len(closes)
    pct_b = [0.5] * n
    for i in range(n):
        band_width = upper[i] - lower[i]
        if band_width > 0:
            pct_b[i] = (closes[i] - lower[i]) / band_width
        else:
            pct_b[i] = 0.5
    return pct_b
