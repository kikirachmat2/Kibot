import asyncio
import pytest
import time
from unittest.mock import patch, MagicMock

from storage.durable_state import durable_state_store, DurableStateStore
from storage.venue_ledger import venue_ledger, VenueLedger
from executor.virtual_ledger import VirtualLedger
from enrichment.candle_manager import CandleEnrichmentManager
from council.swing_evaluator import SwingEvaluator


def test_durable_state_get_latest_snapshot():
    """
    Validates that DurableStateStore has get_latest_snapshot() method
    and returns a valid state dictionary.
    """
    store = DurableStateStore()
    snapshot = store.get_latest_snapshot()
    assert isinstance(snapshot, dict)
    assert "cash_idr" in snapshot or "equity_idr" in snapshot
    assert "open_positions" in snapshot


def test_venue_ledger_reconcile_without_exception():
    """
    Validates that VenueLedger.reconcile_once() executes cleanly
    without throwing 'DurableStateStore object has no attribute get_latest_snapshot'.
    """
    vl = VirtualLedger(initial_cash_idr=10_000_000.0)
    res = asyncio.run(venue_ledger.reconcile_once(vl))
    assert isinstance(res, dict)
    assert res.get("status") == "PASS"
    assert "cash_drift_idr" in res


def test_candle_manager_process_candles_and_indicators():
    """
    Validates CandleEnrichmentManager OHLCV parsing and indicator calculation.
    """
    manager = CandleEnrichmentManager()

    # Generate 120 synthetic daily bars with an upward trend
    synthetic_bars = []
    base_price = 1_000_000_000.0
    for i in range(120):
        price = base_price * (1.0 + (i * 0.005)) # steady +0.5% daily rise
        bar = {
            "Time": 1740000000 + (i * 86400),
            "Open": price * 0.995,
            "High": price * 1.010,
            "Low": price * 0.990,
            "Close": price,
            "Volume": 100.0 + (i * 1.5),
        }
        synthetic_bars.append(bar)

    computed = manager.process_candles("BTCIDR", synthetic_bars)
    assert computed["price"] == synthetic_bars[-1]["Close"]
    assert computed["ema20"] > 0
    assert computed["ema50"] > 0
    assert computed["ema100"] > 0
    assert computed["ema20"] > computed["ema50"] # Uptrend confirmed
    assert computed["price"] > computed["ema100"]
    assert 0 <= computed["rsi14"] <= 100
    assert computed["atr14"] > 0
    assert computed["choppiness_index"] < 61.8 # Strong trend CI should be low
    assert computed["bars_count"] == 120


def test_candle_manager_update_live_price():
    """
    Validates live price tick update in CandleEnrichmentManager.
    """
    manager = CandleEnrichmentManager()
    synthetic_bars = []
    base_price = 50_000_000.0
    for i in range(100):
        synthetic_bars.append({
            "Time": 1740000000 + (i * 86400),
            "Open": base_price,
            "High": base_price * 1.01,
            "Low": base_price * 0.99,
            "Close": base_price,
            "Volume": 50.0,
        })

    manager.process_candles("ETHIDR", synthetic_bars)
    cached_before = manager.get_indicators("ETHIDR")
    assert cached_before["price"] == base_price

    # New tick price surges +2.0%
    new_price = base_price * 1.02
    updated = manager.update_live_price("ETH/IDR", new_price)
    assert updated["price"] == new_price
    assert manager.get_indicators("ETHIDR")["price"] == new_price


def test_end_to_end_candidate_evaluation_with_candle_manager():
    """
    Validates that a candidate enriched by CandleEnrichmentManager
    is successfully processed and APPROVED by SwingEvaluator.
    """
    manager = CandleEnrichmentManager()
    evaluator = SwingEvaluator()

    # Generate 120 trending daily bars for BTC with healthy RSI (~61) and low chop (~60)
    synthetic_bars = []
    price = 900_000_000.0
    for i in range(120):
        if i % 2 == 0:
            ret = -0.004
        else:
            ret = 0.006
        price = price * (1.0 + ret)
        synthetic_bars.append({
            "Time": 1740000000 + (i * 86400),
            "Open": price * 0.998,
            "High": price * 1.004,
            "Low": price * 0.996,
            "Close": price,
            "Volume": 150.0 + (30.0 if i > 100 else 0.0),
        })

    computed = manager.process_candles("BTCIDR", synthetic_bars)
    
    # Simulate candidate payload created in main.py
    candidate_payload = {
        "symbol": "BTC/IDR",
        "price": computed["price"],
        "spread_pct": 0.001,
        "volume_idr": 1_000_000_000.0,
        "volume_ratio": 2.0,
        "leadlag_score": 0.5,
        "binance_momentum_1h": 0.005,
        "binance_is_dumping": False,
        # Injected indicators from CandleEnrichmentManager
        "ema20": computed["ema20"],
        "ema50": computed["ema50"],
        "ema100": computed["ema100"],
        "rsi14": computed["rsi14"],
        "atr14": computed["atr14"],
        "volume": computed["volume"],
        "volume_sma20": computed["volume_sma20"],
        "lower_bb": computed["lower_bb"],
        "middle_bb": computed["middle_bb"],
        "upper_bb": computed["upper_bb"],
        "adx14": computed["adx14"],
        "sma20_slope": computed["sma20_slope"],
        "choppiness_index": computed["choppiness_index"],
        "volume_zscore": computed["volume_zscore"],
        "bollinger_pct_b": computed["bollinger_pct_b"],
    }

    decision = evaluator.evaluate(candidate_payload, bankroll_idr=10_000_000.0)
    assert decision.verdict == "APPROVED"
    assert decision.strategy == "TREND_FOLLOWING"
    assert decision.suggested_size_idr > 0
