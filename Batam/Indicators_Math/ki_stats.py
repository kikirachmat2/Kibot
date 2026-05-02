from __future__ import annotations

import math
from statistics import StatisticsError, mean, pstdev
from typing import Iterable, List

def calculate_z_score(prices, period=20):
    """
    Calculates the Z-Score for the last price in the series.
    Z = (Price - SMA) / STD
    """
    window = _normalize_prices(prices)[-period:]
    if len(window) < period:
        return 0.0

    try:
        last_price = window[-1]
        last_sma = mean(window)
        last_std = pstdev(window)
    except (StatisticsError, ValueError, TypeError):
        return 0.0

    if not math.isfinite(last_price) or not math.isfinite(last_sma) or not math.isfinite(last_std):
        return 0.0
    if last_std == 0:
        return 0.0

    return float((last_price - last_sma) / last_std)

def is_spike(prices, threshold=2.0):
    """
    Returns True if the current price is a statistical spike (Z-Score > threshold)
    """
    z = calculate_z_score(prices)
    return abs(z) >= threshold


def _normalize_prices(prices: Iterable[float]) -> List[float]:
    normalized: List[float] = []
    for raw in prices:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            normalized.append(value)
    return normalized
