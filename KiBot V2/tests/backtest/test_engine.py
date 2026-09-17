"""
Unit tests for KiBot V2 Backtest Engine.
Runs fully offline with synthetic dummy fixtures (20-50 bars).
"""
import pandas as pd
import numpy as np
import pytest

from backtest.engine import run_backtest, _compute_indicators, _is_bar_skipped
from backtest.friction import OrderType


@pytest.fixture
def dummy_aligned_df():
    """Generates 40 bars of realistic dummy aligned Indodax/Binance data."""
    base_ts = 1700000000
    rows = []
    price = 500_000_000.0

    for i in range(40):
        # Create small price oscillations
        ts = base_ts + (i * 3600)
        open_p = price
        if i == 25:
            # Dip below lower BB to trigger MR signal
            close_p = open_p * 0.96
            high_p = open_p * 1.002
            low_p = close_p * 0.995
        elif i == 26:
            # Entry bar: open equals prev close, price rebounds
            close_p = open_p * 1.025
            high_p = close_p * 1.01
            low_p = open_p * 0.999
        else:
            close_p = open_p * 1.001
            high_p = max(open_p, close_p) * 1.002
            low_p = min(open_p, close_p) * 0.998

        price = close_p
        rows.append({
            "timestamp_utc": ts,
            "indo_open": open_p,
            "indo_high": high_p,
            "indo_low": low_p,
            "indo_close": close_p,
            "indo_volume": 2.5,
            "binance_open": open_p / 15000,
            "binance_high": high_p / 15000,
            "binance_low": low_p / 15000,
            "binance_close": close_p / 15000,
            "binance_volume": 100.0,
            "indo_return_1h": (close_p - open_p) / open_p,
            "binance_return_1h": (close_p - open_p) / open_p,
            "dislocation_1h": 0.0,
        })

    return pd.DataFrame(rows)


def test_no_look_ahead_indicators(dummy_aligned_df):
    """Verifies indicators at bar[i] are identical whether future bars exist or not."""
    df_full = _compute_indicators(dummy_aligned_df, "BTCIDR")
    df_sub = _compute_indicators(dummy_aligned_df.iloc[:25], "BTCIDR")

    # Bar 24 middle_bb, lower_bb must be bit-for-bit identical
    assert df_full.loc[24, "middle_bb"] == pytest.approx(df_sub.loc[24, "middle_bb"])
    assert df_full.loc[24, "lower_bb"] == pytest.approx(df_sub.loc[24, "lower_bb"])
    assert df_full.loc[24, "upper_bb"] == pytest.approx(df_sub.loc[24, "upper_bb"])


def test_entry_executed_at_next_bar_open(dummy_aligned_df):
    """Verifies entry occurs at bar[i+1].open, NOT at bar[i].close."""
    res = run_backtest(
        aligned_df=dummy_aligned_df,
        strategy_name="D1",
        pair="BTCIDR",
        initial_capital_idr=10_000_000.0,
        position_size_idr=5_000_000.0,
        order_type=OrderType.TAKER,  # 100% fill for determinism
    )

    trades = res["trades_log"]
    assert len(trades) >= 1, "Should have triggered at least one trade on dip"
    trade = trades[0]

    # Signal triggered at bar 25 dip
    expected_entry_ts = dummy_aligned_df.loc[26, "timestamp_utc"]
    expected_entry_price = dummy_aligned_df.loc[26, "indo_open"]

    assert trade["entry_ts"] == expected_entry_ts
    assert trade["entry_price"] == pytest.approx(expected_entry_price)


def test_worst_case_sl_priority_when_tp_and_sl_hit_same_bar():
    """Verifies that if both TP and SL are hit in the same bar, SL is prioritized (worst-case)."""
    rows = []
    base_ts = 1700000000
    p = 100_000_000.0

    # 25 upward-sloping calm bars (so lower_bb is strictly below low)
    for i in range(25):
        price = p + (i * 200_000)
        rows.append({
            "timestamp_utc": base_ts + (i * 3600),
            "indo_open": price, "indo_high": price * 1.002, "indo_low": price * 0.999, "indo_close": price * 1.001,
            "indo_volume": 1.0,
            "binance_open": price / 1000, "binance_high": (price * 1.002) / 1000,
            "binance_low": (price * 0.999) / 1000, "binance_close": (price * 1.001) / 1000,
            "binance_volume": 10.0, "indo_return_1h": 0.001, "binance_return_1h": 0.001, "dislocation_1h": 0.0,
        })

    # Bar 25: sharp plunge triggers MR signal
    rows.append({
        "timestamp_utc": base_ts + (25 * 3600),
        "indo_open": price, "indo_high": price, "indo_low": price * 0.85, "indo_close": price * 0.86,
        "indo_volume": 2.0,
        "binance_open": price / 1000, "binance_high": price / 1000,
        "binance_low": (price * 0.85) / 1000, "binance_close": (price * 0.86) / 1000,
        "binance_volume": 10.0, "indo_return_1h": -0.14, "binance_return_1h": -0.14, "dislocation_1h": 0.0,
    })

    # Bar 26: entry executes at open, then intra-bar hits BOTH TP (+20%) and SL (-20%)
    rows.append({
        "timestamp_utc": base_ts + (26 * 3600),
        "indo_open": price * 0.86,
        "indo_high": price * 1.20,  # hits TP
        "indo_low": price * 0.70,   # hits SL
        "indo_close": price * 0.86,
        "indo_volume": 10.0,
        "binance_open": (price * 0.86) / 1000, "binance_high": (price * 1.20) / 1000,
        "binance_low": (price * 0.70) / 1000, "binance_close": (price * 0.86) / 1000,
        "binance_volume": 100.0, "indo_return_1h": 0.0, "binance_return_1h": 0.0, "dislocation_1h": 0.0,
    })

    df = pd.DataFrame(rows)
    res = run_backtest(df, strategy_name="D1", pair="BTCIDR", order_type=OrderType.TAKER)

    assert len(res["trades_log"]) == 1
    trade = res["trades_log"][0]
    assert trade["exit_reason"] == "SL", "When both TP and SL are hit in same bar, SL must take priority"


def test_worst_case_continuous_drop_capital_depletion():
    """Verifies worst-case: price drops continuously, hitting SL; final capital reflects SL + friction."""
    rows = []
    base_ts = 1700000000
    p = 100_000_000.0

    for i in range(25):
        price = p + (i * 200_000)
        rows.append({
            "timestamp_utc": base_ts + (i * 3600),
            "indo_open": price, "indo_high": price * 1.002, "indo_low": price * 0.999, "indo_close": price * 1.001,
            "indo_volume": 1.0,
            "binance_open": price / 1000, "binance_high": (price * 1.002) / 1000,
            "binance_low": (price * 0.999) / 1000, "binance_close": (price * 1.001) / 1000,
            "binance_volume": 10.0, "indo_return_1h": 0.001, "binance_return_1h": 0.001, "dislocation_1h": 0.0,
        })

    # Bar 25: dip to trigger entry
    rows.append({
        "timestamp_utc": base_ts + (25 * 3600),
        "indo_open": price, "indo_high": price, "indo_low": price * 0.85, "indo_close": price * 0.86,
        "indo_volume": 2.0,
        "binance_open": price / 1000, "binance_high": price / 1000,
        "binance_low": (price * 0.85) / 1000, "binance_close": (price * 0.86) / 1000,
        "binance_volume": 10.0, "indo_return_1h": -0.14, "binance_return_1h": -0.14, "dislocation_1h": 0.0,
    })

    # Bar 26: entry executes, price continues plunging straight to SL (-2%)
    entry_p = price * 0.86
    rows.append({
        "timestamp_utc": base_ts + (26 * 3600),
        "indo_open": entry_p,
        "indo_high": entry_p * 1.001,
        "indo_low": entry_p * 0.97,  # drops 3% -> triggers 2% SL
        "indo_close": entry_p * 0.97,
        "indo_volume": 5.0,
        "binance_open": entry_p / 1000, "binance_high": (entry_p * 1.001) / 1000,
        "binance_low": (entry_p * 0.97) / 1000, "binance_close": (entry_p * 0.97) / 1000,
        "binance_volume": 50.0, "indo_return_1h": -0.03, "binance_return_1h": -0.03, "dislocation_1h": 0.0,
    })

    df = pd.DataFrame(rows)
    initial_cap = 10_000_000.0
    pos_size = 5_000_000.0
    res = run_backtest(
        df,
        strategy_name="D1",
        pair="BTCIDR",
        initial_capital_idr=initial_cap,
        position_size_idr=pos_size,
        order_type=OrderType.MAKER,  # Maker friction = 0.56%
        sl_pct=0.02,                 # SL = 2.0%
        random_seed=42,
    )

    assert len(res["trades_log"]) == 1
    t = res["trades_log"][0]
    assert t["exit_reason"] == "SL"

    # Expected calculations:
    # Gross loss = 5_000_000 * -0.02 = -100_000 IDR
    # Maker friction = 5_000_000 * 0.0056 = 28_000 IDR
    # Adverse penalty = 0.0 IDR
    # Net loss = -128_000 IDR
    assert t["gross_pnl_idr"] == -100_000.0
    assert t["friction_idr"] == 28_000.0
    assert t["net_pnl_idr"] == -128_000.0
    assert res["net_pnl_idr"] == -128_000.0


def test_skip_zero_volume_and_flat_bars():
    """Verifies that bars with volume == 0 or high == low are skipped."""
    row_zero_vol = pd.Series({"indo_volume": 0.0, "indo_high": 100.0, "indo_low": 99.0})
    row_flat = pd.Series({"indo_volume": 5.0, "indo_high": 100.0, "indo_low": 100.0})
    row_clean = pd.Series({"indo_volume": 5.0, "indo_high": 101.0, "indo_low": 99.0})
    row_sol_narrow = pd.Series({"indo_volume": 5.0, "indo_high": 100.03, "indo_low": 100.0})  # 0.03%

    assert _is_bar_skipped(row_zero_vol, "BTCIDR") is True
    assert _is_bar_skipped(row_flat, "BTCIDR") is True
    assert _is_bar_skipped(row_clean, "BTCIDR") is False

    # SOLIDR 0.05% range check
    assert _is_bar_skipped(row_sol_narrow, "SOLIDR") is True
    assert _is_bar_skipped(row_clean, "SOLIDR") is False


def test_max_two_concurrent_positions(dummy_aligned_df):
    """Verifies that engine never opens more than 2 concurrent positions (dual slot)."""
    res = run_backtest(
        aligned_df=dummy_aligned_df,
        strategy_name="D1",
        pair="BTCIDR",
        initial_capital_idr=10_000_000.0,
        position_size_idr=5_000_000.0,
    )
    # Check trade log overlaps
    trades = res["trades_log"]
    for i, t1 in enumerate(trades):
        concurrent = 1
        for j, t2 in enumerate(trades):
            if i != j and not (t2["exit_ts"] <= t1["entry_ts"] or t2["entry_ts"] >= t1["exit_ts"]):
                concurrent += 1
        assert concurrent <= 2, f"Concurrent positions exceeded 2: got {concurrent}"


def test_trade_log_required_columns_and_exit_reasons(dummy_aligned_df):
    """Verifies exact schema and valid exit reasons in trade log."""
    res = run_backtest(dummy_aligned_df, strategy_name="D1", pair="BTCIDR")
    required_cols = [
        "entry_ts", "entry_price", "exit_ts", "exit_price", "side",
        "size_idr", "gross_pnl_idr", "friction_idr", "adverse_penalty_idr",
        "net_pnl_idr", "exit_reason",
    ]
    valid_reasons = {"TP", "SL", "TIMEOUT", "INVALIDATION", "STAGNATION", "END_OF_DATA", "TRAILING_ATR", "EXIT_RSI50", "EXIT_ZSCORE"}

    for trade in res["trades_log"]:
        for col in required_cols:
            assert col in trade, f"Missing required column: {col}"
        assert trade["exit_reason"] in valid_reasons, f"Invalid exit reason: {trade['exit_reason']}"


def test_engine_determinism(dummy_aligned_df):
    """Verifies that running backtest twice with identical seed produces identical results."""
    res1 = run_backtest(dummy_aligned_df, strategy_name="D1", pair="BTCIDR", random_seed=123)
    res2 = run_backtest(dummy_aligned_df, strategy_name="D1", pair="BTCIDR", random_seed=123)

    assert res1["net_pnl_idr"] == res2["net_pnl_idr"]
    assert res1["n_trades"] == res2["n_trades"]
    assert res1["win_rate"] == res2["win_rate"]
    assert res1["trades_log"] == res2["trades_log"]


def test_higher_timeframe_strategies_execution(dummy_aligned_df):
    """Verifies TREND_1D, MR_4H, and MR_1D execute properly without runtime error."""
    for strat in ["TREND_1D", "MR_4H", "MR_1D"]:
        res = run_backtest(
            dummy_aligned_df,
            strategy_name=strat,
            pair="BTCIDR",
            order_type=OrderType.TAKER,
        )
        assert "net_pnl_idr" in res
        assert "n_trades" in res
        assert "max_drawdown_pct" in res
        assert isinstance(res["trades_log"], list)

