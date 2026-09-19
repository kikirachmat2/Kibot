"""
KiBot V2 — Market Regime Detector & BTC.D Rotation Engine.
Synthesizes FlowTrinity & RegimeRisk quantitative models:
- Trend direction: EMA 21 / 55 cross
- Trend strength: ADX 14 + Wilder's smoothing (ADX < 20 indicates sideways/range)
- Momentum & Direction: RSI 14 + DI+ / DI- directional voting
- Composite score: -2.5 (strong bear) to +2.5 (strong bull)
- Regime classification: BULL, BEAR, RANGE, UNKNOWN
- BTC Dominance 7H trend & Altcoin Rotation Scoring (0 - 100)
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Dict, Any, Optional, Union
import numpy as np
import pandas as pd

logger = logging.getLogger("KiBotV2.RegimeDetector")


class MarketRegime(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    RANGE = "range"
    UNKNOWN = "unknown"


def calc_adx_dmi(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Calculates ADX, +DI, and -DI using Wilder's directional movement smoothing."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Wilder's smoothing (alpha = 1 / period)
    alpha = 1.0 / period
    tr_smooth = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_dm_smooth = pd.Series(plus_dm, index=df.index).ewm(alpha=alpha, adjust=False).mean()
    minus_dm_smooth = pd.Series(minus_dm, index=df.index).ewm(alpha=alpha, adjust=False).mean()

    plus_di = 100.0 * (plus_dm_smooth / (tr_smooth + 1e-12))
    minus_di = 100.0 * (minus_dm_smooth / (tr_smooth + 1e-12))

    dx = 100.0 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-12))
    adx = dx.ewm(alpha=alpha, adjust=False).mean()

    return adx, plus_di, minus_di


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    alpha = 1.0 / period
    avg_gain = pd.Series(gain, index=series.index).ewm(alpha=alpha, adjust=False).mean()
    avg_loss = pd.Series(loss, index=series.index).ewm(alpha=alpha, adjust=False).mean()

    rs = avg_gain / (avg_loss + 1e-12)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def detect_regime(
    btc_ohlcv_1h: pd.DataFrame,
    btc_dominance_series: Optional[pd.Series] = None,
    alt_volume_ratio: float = 1.0,
    lookback: int = 200,
) -> Dict[str, Any]:
    """
    Evaluates market regime using composite technical indicators and BTC dominance flow.
    Returns:
    {
      "regime": MarketRegime,
      "strength": float,  # 0 - 100
      "btc_trend_7h": float,
      "btc_dominance_trend_7h": float,
      "altcoin_rotation_score": float,  # 0 - 100
      "signals": {...}
    }
    """
    if btc_ohlcv_1h is None or len(btc_ohlcv_1h) < 30:
        return {
            "regime": MarketRegime.UNKNOWN,
            "strength": 0.0,
            "btc_trend_7h": 0.0,
            "btc_dominance_trend_7h": 0.0,
            "altcoin_rotation_score": 0.0,
            "signals": {"reason": "insufficient_data"},
        }

    df = btc_ohlcv_1h.copy()
    close = df["close"].astype(float)

    # 1. EMA 21 and EMA 55 trend direction
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema55 = close.ewm(span=55, adjust=False).mean()

    # 2. ADX 14, +DI, -DI
    adx_series, plus_di, minus_di = calc_adx_dmi(df, period=14)

    # 3. RSI 14
    rsi_series = calc_rsi(close, period=14)

    # Latest values
    curr_close = float(close.iloc[-1])
    curr_ema21 = float(ema21.iloc[-1])
    curr_ema55 = float(ema55.iloc[-1])
    curr_adx = float(adx_series.iloc[-1])
    curr_plus_di = float(plus_di.iloc[-1])
    curr_minus_di = float(minus_di.iloc[-1])
    curr_rsi = float(rsi_series.iloc[-1])

    # 4. BTC 7H trend
    if len(close) >= 8:
        prev_7h = float(close.iloc[-8])
        btc_trend_7h = ((curr_close - prev_7h) / prev_7h * 100.0) if prev_7h > 0 else 0.0
    else:
        btc_trend_7h = 0.0

    # 5. BTC Dominance 7H trend
    btcd_trend_7h = 0.0
    if btc_dominance_series is not None and len(btc_dominance_series) >= 8:
        cur_d = float(btc_dominance_series.iloc[-1])
        old_d = float(btc_dominance_series.iloc[-8])
        btcd_trend_7h = ((cur_d - old_d) / old_d * 100.0) if old_d > 0 else 0.0
    elif btc_dominance_series is not None and len(btc_dominance_series) > 1:
        cur_d = float(btc_dominance_series.iloc[-1])
        old_d = float(btc_dominance_series.iloc[0])
        btcd_trend_7h = ((cur_d - old_d) / old_d * 100.0) if old_d > 0 else 0.0

    # 6. Composite Score Calculation (-2.5 to +2.5)
    # EMA trend vote (+1.0 / -1.0)
    ema_vote = 1.0 if curr_ema21 > curr_ema55 else -1.0

    # DMI directional vote (+0.5 / -0.5)
    dmi_vote = 0.5 if curr_plus_di > curr_minus_di else -0.5

    # RSI momentum vote (+1.0 / -1.0 / 0.0)
    if curr_rsi >= 55.0:
        rsi_vote = 1.0
    elif curr_rsi <= 45.0:
        rsi_vote = -1.0
    else:
        rsi_vote = 0.0

    composite_score = ema_vote + dmi_vote + rsi_vote

    # 7. Classification logic
    if curr_adx < 20.0:
        regime = MarketRegime.RANGE
    elif composite_score >= 1.5 and curr_rsi >= 60.0:
        regime = MarketRegime.BULL
    elif composite_score <= -1.5 and curr_rsi <= 40.0:
        regime = MarketRegime.BEAR
    else:
        # Defaults to RANGE when not clear breakout
        regime = MarketRegime.RANGE

    # Strength indicator: ADX scaled (0-100)
    strength = round(min(100.0, max(0.0, curr_adx)), 1)

    # 8. Altcoin Rotation Score (0 to 100)
    # - BTC.D down (> 0.5% drop in 7h) -> +40 pts
    # - BTC Range / Sideways -> +30 pts
    # - Altcoin volume expansion (ratio >= 2.0) -> +30 pts
    rot_score = 0.0
    if btcd_trend_7h < -0.5:
        rot_score += 40.0
    elif btcd_trend_7h < 0.0:
        rot_score += 20.0

    if regime in (MarketRegime.RANGE, MarketRegime.UNKNOWN):
        rot_score += 30.0
    elif regime == MarketRegime.BULL and btcd_trend_7h < 0.0:
        rot_score += 15.0

    if alt_volume_ratio >= 2.0:
        rot_score += 30.0
    elif alt_volume_ratio >= 1.5:
        rot_score += 15.0

    return {
        "regime": regime,
        "strength": strength,
        "btc_trend_7h": round(btc_trend_7h, 2),
        "btc_dominance_trend_7h": round(btcd_trend_7h, 2),
        "altcoin_rotation_score": round(min(100.0, rot_score), 1),
        "signals": {
            "composite_score": round(composite_score, 2),
            "ema21": round(curr_ema21, 2),
            "ema55": round(curr_ema55, 2),
            "rsi14": round(curr_rsi, 1),
            "adx14": round(curr_adx, 1),
            "plus_di": round(curr_plus_di, 1),
            "minus_di": round(curr_minus_di, 1),
            "curr_price": round(curr_close, 2),
        },
    }
