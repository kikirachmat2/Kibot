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
    Now verifies the two-cache separation: strategy (closed) vs live.
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

    # process_candles now returns (strategy_computed, live_computed)
    strategy_computed, live_computed = manager.process_candles("BTCIDR", synthetic_bars)
    # All bars have past timestamps => all are closed => strategy == live indicators
    assert strategy_computed["price"] == synthetic_bars[-1]["Close"]
    assert strategy_computed["ema20"] > 0
    assert strategy_computed["ema50"] > 0
    assert strategy_computed["ema100"] > 0
    assert strategy_computed["ema20"] > strategy_computed["ema50"] # Uptrend confirmed
    assert strategy_computed["price"] > strategy_computed["ema100"]
    assert 0 <= strategy_computed["rsi14"] <= 100
    assert strategy_computed["atr14"] > 0
    assert strategy_computed["choppiness_index"] < 61.8 # Strong trend CI should be low
    assert strategy_computed["bars_count"] == 120
    # get_strategy_indicators convenience method should return same result
    cached = manager.get_strategy_indicators("BTCIDR")
    assert cached is not None
    assert cached["price"] == strategy_computed["price"]


def test_candle_manager_update_live_price():
    """
    Validates live price tick update in CandleEnrichmentManager.
    Confirms that update_live_price() only mutates the live cache,
    NOT the strategy (closed-bar) cache (D-08 Fix A).
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

    strategy_before = manager.get_strategy_indicators("ETHIDR")
    strategy_price_before = strategy_before["price"]

    # New tick price surges +2.0%
    new_price = base_price * 1.02
    updated = manager.update_live_price("ETH/IDR", new_price)
    assert updated["price"] == new_price
    assert manager.get_indicators("ETHIDR")["price"] == new_price

    # CRITICAL: Strategy cache must NOT be contaminated by the live tick
    strategy_after = manager.get_strategy_indicators("ETHIDR")
    assert strategy_after["price"] == strategy_price_before, (
        "update_live_price() must not modify strategy indicators (look-ahead prevention)"
    )


def test_end_to_end_candidate_evaluation_with_candle_manager():
    """
    Validates that a candidate enriched by CandleEnrichmentManager
    is successfully processed and APPROVED by SwingEvaluator.
    Also validates: Binance UNKNOWN status blocks entry; OK status passes.
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

    strategy_computed, _ = manager.process_candles("BTCIDR", synthetic_bars)
    computed = strategy_computed  # alias for readability

    # Test 1: With binance_data_status UNKNOWN (default) — must be REJECTED fail-closed
    candidate_unknown = {
        "symbol": "BTC/IDR",
        "price": computed["price"],
        "spread_pct": 0.001,
        "volume_idr": 1_000_000_000.0,
        "volume_ratio": 2.0,
        "leadlag_score": 0.5,
        "binance_momentum_1h": 0.005,
        "binance_is_dumping": False,
        # NO binance_data_status field (defaults to UNKNOWN in extract_indicator_values)
        **{k: computed[k] for k in [
            "ema20", "ema50", "ema100", "rsi14", "atr14", "volume",
            "volume_sma20", "lower_bb", "middle_bb", "upper_bb",
            "adx14", "sma20_slope", "choppiness_index", "volume_zscore", "bollinger_pct_b",
        ]},
    }
    decision_unknown = evaluator.evaluate(candidate_unknown, bankroll_idr=10_000_000.0)
    assert decision_unknown.verdict == "REJECTED"
    assert decision_unknown.enrichment_status == "BINANCE_DATA_UNKNOWN"

    # Test 2: With binance_data_status OK — should be APPROVED (assuming trend conditions met)
    candidate_ok = dict(candidate_unknown)
    candidate_ok["binance_data_status"] = "OK"
    decision_ok = evaluator.evaluate(candidate_ok, bankroll_idr=10_000_000.0)
    assert decision_ok.verdict == "APPROVED"
    assert decision_ok.strategy == "TREND_FOLLOWING"
    assert decision_ok.suggested_size_idr > 0
