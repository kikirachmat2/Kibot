"""
D-09 Regression Tests — Open 1D Bar Isolation (Task 1)

Ensures CandleEnrichmentManager correctly separates strategy indicators
(closed bars only) from live indicators (includes the open/current bar).

Invariants under test:
1. bars_count in strategy cache == number of explicitly CLOSED bars.
2. Price in strategy cache == last CLOSED bar's close (NOT the open bar price).
3. update_live_price() mutates ONLY the live cache; strategy cache is immutable.
4. Extreme price move on the open bar does NOT contaminate strategy indicators.
5. When closed bars < 100, strategy cache is empty → entry blocked.
"""
import time
import calendar
import datetime

import pytest

from enrichment.candle_manager import CandleEnrichmentManager


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _today_utc_midnight_ts() -> float:
    """
    Returns the UNIX timestamp of 00:00:00 UTC **today** (UTC date).
    Uses calendar.timegm so it is immune to the machine's local timezone.
    """
    today_utc = datetime.datetime.now(datetime.timezone.utc).date()
    return float(calendar.timegm(today_utc.timetuple()))


def _make_bars(n_closed: int, include_open_bar: bool, open_bar_price: float = None):
    """
    Build synthetic 1D OHLCV bars.

    Closed bars are anchored 200 days ago, each 1 day apart (all safely in the past).
    The optional open bar uses today's UTC midnight timestamp (correctly computed
    via calendar.timegm, not local-timezone datetime.combine).

    Returns (bars_list, last_closed_price).
    """
    bars = []
    base_price = 1_000_000_000.0
    last_closed_price = base_price

    # Anchor 200 days in the past — all closed bars will be well before today UTC
    anchor_ts = time.time() - (200 * 86400)

    for i in range(n_closed):
        price = base_price * (1.0 + i * 0.001)
        ts = anchor_ts + i * 86400  # 1 day apart, all historical
        bars.append({
            "Time":   ts,
            "Open":   price * 0.995,
            "High":   price * 1.010,
            "Low":    price * 0.990,
            "Close":  price,
            "Volume": 100.0 + i,
        })
        last_closed_price = price

    if include_open_bar:
        # Correct UTC midnight timestamp (timezone-immune)
        today_utc_ts = _today_utc_midnight_ts()
        if open_bar_price is None:
            open_bar_price = last_closed_price * 2.0  # extreme move
        bars.append({
            "Time":   today_utc_ts,
            "Open":   open_bar_price * 0.99,
            "High":   open_bar_price * 1.05,
            "Low":    open_bar_price * 0.90,
            "Close":  open_bar_price,
            "Volume": 999_999.0,   # abnormally large to make contamination obvious
        })

    return bars, last_closed_price


# ---------------------------------------------------------------------------
# Test 1 — Baseline: all closed bars → strategy == live (same price)
# ---------------------------------------------------------------------------

def test_all_closed_bars_strategy_equals_live_price():
    """No open bar → strategy and live must agree on price and bars_count."""
    manager = CandleEnrichmentManager()
    bars, last_price = _make_bars(n_closed=120, include_open_bar=False)
    strategy, live = manager.process_candles("BTCIDR", bars)

    assert strategy, "strategy_computed must not be empty for 120 closed bars"
    assert strategy["bars_count"] == 120
    assert strategy["price"] == pytest.approx(last_price, rel=1e-6)
    assert live["price"] == pytest.approx(last_price, rel=1e-6)
    assert strategy.get("_source") == "CLOSED_BARS_ONLY"


# ---------------------------------------------------------------------------
# Test 2 — Core invariant: 100 closed + 1 open bar
# ---------------------------------------------------------------------------

def test_open_bar_excluded_from_strategy_cache():
    """
    100 closed bars + 1 current-day open bar:
      - strategy bars_count == 100 (open bar excluded)
      - strategy price == last closed bar price (NOT the open bar price)
      - live price == open bar price
    """
    manager = CandleEnrichmentManager()
    open_bar_price = 999_999_999.0   # extreme — must NOT appear in strategy
    bars, last_closed_price = _make_bars(
        n_closed=100, include_open_bar=True, open_bar_price=open_bar_price
    )
    strategy, live = manager.process_candles("BTCIDR", bars)

    assert strategy, "100 closed bars must yield valid strategy indicators"
    assert strategy["bars_count"] == 100, (
        f"Expected bars_count=100, got {strategy['bars_count']}"
    )
    assert strategy["price"] == pytest.approx(last_closed_price, rel=1e-6), (
        f"Strategy price must equal last CLOSED bar ({last_closed_price:,.0f}), "
        f"NOT the open bar ({open_bar_price:,.0f})"
    )
    assert live["price"] == pytest.approx(open_bar_price, rel=1e-6)
    assert strategy.get("_source") == "CLOSED_BARS_ONLY"


# ---------------------------------------------------------------------------
# Test 3 — get_strategy_indicators() accessor returns closed-only snapshot
# ---------------------------------------------------------------------------

def test_get_strategy_indicators_returns_closed_only():
    """
    get_strategy_indicators() must return closed-bar snapshot;
    get_indicators() must return live snapshot (includes open bar).
    """
    manager = CandleEnrichmentManager()
    open_bar_price = 5_000_000_000.0  # wildly different
    bars, last_closed_price = _make_bars(
        n_closed=110, include_open_bar=True, open_bar_price=open_bar_price
    )
    manager.process_candles("BTCIDR", bars)

    strat = manager.get_strategy_indicators("BTCIDR")
    live  = manager.get_indicators("BTCIDR")

    assert strat is not None
    assert strat["bars_count"] == 110
    assert strat["price"] == pytest.approx(last_closed_price, rel=1e-6)
    assert live["price"] == pytest.approx(open_bar_price, rel=1e-6)
    # Prices must differ — extreme open bar makes this obvious
    assert abs(strat["price"] - live["price"]) > 1_000_000


# ---------------------------------------------------------------------------
# Test 4 — update_live_price() must NOT touch strategy cache
# ---------------------------------------------------------------------------

def test_update_live_price_does_not_contaminate_strategy_cache():
    """
    After process_candles(), update_live_price() with extreme tick must
    ONLY mutate _live_indicators — _strategy_indicators is immutable.
    """
    manager = CandleEnrichmentManager()
    bars, last_closed_price = _make_bars(n_closed=120, include_open_bar=False)
    manager.process_candles("BTCIDR", bars)

    strat_before = manager.get_strategy_indicators("BTCIDR")
    assert strat_before is not None
    price_before = strat_before["price"]

    extreme_tick = last_closed_price * 10.0
    updated_live = manager.update_live_price("BTCIDR", extreme_tick)

    # Live updated
    assert updated_live["price"] == pytest.approx(extreme_tick, rel=1e-6)
    assert manager.get_indicators("BTCIDR")["price"] == pytest.approx(extreme_tick, rel=1e-6)

    # Strategy completely unchanged
    strat_after = manager.get_strategy_indicators("BTCIDR")
    assert strat_after["price"] == pytest.approx(price_before, rel=1e-9), (
        "update_live_price() must not contaminate strategy indicators"
    )
    assert strat_after["bars_count"] == strat_before["bars_count"]
    assert strat_after.get("_source") == "CLOSED_BARS_ONLY"


# ---------------------------------------------------------------------------
# Test 5 — EMA / RSI / CI stable across extreme live ticks
# ---------------------------------------------------------------------------

def test_strategy_indicators_stable_across_extreme_ticks():
    """
    EMA20, EMA50, RSI14, CI in strategy cache must remain numerically identical
    regardless of what update_live_price() injects (closed-bar immutability).
    """
    manager = CandleEnrichmentManager()
    bars, _ = _make_bars(n_closed=120, include_open_bar=True)
    manager.process_candles("BTCIDR", bars)

    strat_initial = dict(manager.get_strategy_indicators("BTCIDR"))

    for multiplier in [0.001, 1000.0, 0.3, 50.0]:
        manager.update_live_price("BTCIDR", strat_initial["price"] * multiplier)
        s = manager.get_strategy_indicators("BTCIDR")
        assert s["ema20"]            == pytest.approx(strat_initial["ema20"],            rel=1e-9)
        assert s["ema50"]            == pytest.approx(strat_initial["ema50"],            rel=1e-9)
        assert s["rsi14"]            == pytest.approx(strat_initial["rsi14"],            rel=1e-9)
        assert s["choppiness_index"] == pytest.approx(strat_initial["choppiness_index"], rel=1e-9)
        assert s["bars_count"]       == strat_initial["bars_count"]


# ---------------------------------------------------------------------------
# Test 6 — Insufficient closed bars (< 100) → entry blocked
# ---------------------------------------------------------------------------

def test_insufficient_closed_bars_blocks_strategy():
    """
    99 closed bars + 1 open bar = 99 closed:
      - strategy_computed must be empty dict
      - get_strategy_indicators() returns None
      - live_computed still has indicators (total bars = 100 >= 20)
    """
    manager = CandleEnrichmentManager()
    bars, _ = _make_bars(n_closed=99, include_open_bar=True)
    strategy, live = manager.process_candles("BTCIDR", bars)

    assert strategy == {}, (
        "strategy_computed must be empty dict when closed bars < 100"
    )
    assert manager.get_strategy_indicators("BTCIDR") is None, (
        "get_strategy_indicators() must return None when < 100 closed bars"
    )
    assert live, "live_computed must still be populated (total bars = 100 >= 20)"


# ---------------------------------------------------------------------------
# Test 7 — Boundary: exactly 100 closed bars + 1 open bar
# ---------------------------------------------------------------------------

def test_exactly_100_closed_bars_plus_open_bar_boundary():
    """
    Boundary: exactly 100 closed bars + 1 open bar.
    strategy_computed must be non-empty with bars_count == 100 (not 101).
    """
    manager = CandleEnrichmentManager()
    bars, last_closed_price = _make_bars(n_closed=100, include_open_bar=True)
    strategy, live = manager.process_candles("AVAXIDR", bars)

    assert strategy, "Exactly 100 closed bars must produce valid strategy indicators"
    assert strategy["bars_count"] == 100, (
        f"bars_count must be 100 (open bar excluded), got {strategy['bars_count']}"
    )
    assert strategy["price"] == pytest.approx(last_closed_price, rel=1e-6)
