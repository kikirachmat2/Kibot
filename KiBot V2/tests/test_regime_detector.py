import pytest
import numpy as np
import pandas as pd

from council.regime_detector import detect_regime, MarketRegime

def make_ohlcv(closes, high_offset=0.01, low_offset=0.01, volume=1000.0):
    closes = np.array(closes, dtype=float)
    highs = closes * (1.0 + high_offset)
    lows = closes * (1.0 - low_offset)
    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    volumes = np.full_like(closes, volume)
    return pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })

def test_bull_regime_scenario():
    # Linear upward trend: 100 to 200 over 100 bars
    closes = np.linspace(100.0, 250.0, 100)
    df = make_ohlcv(closes)
    
    # BTC.D trend flat
    btcd = pd.Series(np.linspace(55.0, 56.0, 20))
    res = detect_regime(df, btc_dominance_series=btcd)
    
    assert res["regime"] == MarketRegime.BULL
    assert res["signals"]["rsi14"] >= 60.0
    assert res["signals"]["ema21"] > res["signals"]["ema55"]
    assert res["strength"] > 20.0

def test_bear_regime_scenario():
    # Linear downward trend: 200 to 100 over 100 bars
    closes = np.linspace(250.0, 100.0, 100)
    df = make_ohlcv(closes)
    
    res = detect_regime(df)
    assert res["regime"] == MarketRegime.BEAR
    assert res["signals"]["rsi14"] <= 40.0
    assert res["signals"]["ema21"] < res["signals"]["ema55"]

def test_range_regime_scenario():
    # Flat sideways oscillation with small amplitude (low ADX < 20)
    np.random.seed(42)
    closes = 100.0 + np.sin(np.linspace(0, 20 * np.pi, 100)) * 0.5
    df = make_ohlcv(closes, high_offset=0.002, low_offset=0.002)
    
    res = detect_regime(df)
    assert res["regime"] == MarketRegime.RANGE
    assert res["signals"]["adx14"] < 20.0

def test_altcoin_rotation_score():
    # Range market + BTC.D dropping sharply + altcoin volume spike
    closes = 100.0 + np.sin(np.linspace(0, 20 * np.pi, 100)) * 0.5
    df = make_ohlcv(closes, high_offset=0.002, low_offset=0.002)
    
    # BTC.D drops from 55.0 to 53.0 (-3.6%)
    btcd = pd.Series(np.linspace(55.0, 53.0, 10))
    res = detect_regime(df, btc_dominance_series=btcd, alt_volume_ratio=2.5)
    
    # 40 (BTC.D drop) + 30 (RANGE) + 30 (Vol ratio >= 2.0) = 100
    assert res["altcoin_rotation_score"] == 100.0
