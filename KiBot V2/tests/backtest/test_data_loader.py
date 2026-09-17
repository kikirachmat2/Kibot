"""
Unit tests for KiBot V2 Backtest Data Loader.
Tests run completely offline using mocked HTTP sessions and temporary directory fixtures.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from backtest.data_loader import (
    fetch_indodax_ohlcv,
    fetch_binance_ohlcv,
    align_indodax_binance,
    _validate_no_gaps,
)


def _make_mock_indodax_response(start_ts: int, count: int, step: int = 3600):
    """Builds synthetic Indodax TradingView API response list."""
    bars = []
    price = 1_000_000_000.0
    for i in range(count):
        bars.append({
            "Time": start_ts + (i * step),
            "Open": price,
            "High": price + 5_000_000.0,
            "Low": price - 5_000_000.0,
            "Close": price + 1_000_000.0,
            "Volume": "1.5",
        })
        price += 1_000_000.0
    return bars


def _make_mock_binance_response(start_ts: int, count: int, step: int = 3600):
    """Builds synthetic Binance klines list of lists."""
    bars = []
    price = 65000.0
    for i in range(count):
        ts_ms = (start_ts + (i * step)) * 1000
        bars.append([
            ts_ms,
            str(price),
            str(price + 200.0),
            str(price - 200.0),
            str(price + 50.0),
            "10.5",
            ts_ms + (step * 1000) - 1,
            "682500.0",
            100,
            "5.2",
            "338000.0",
            "0",
        ])
        price += 50.0
    return bars


def test_cache_miss_then_hit_indodax(tmp_path: Path):
    """Verifies that first call fetches via HTTP and writes cache; second call reads from cache without HTTP."""
    start_ts = 1672531200  # 2023-01-01 00:00:00 UTC
    mock_data = _make_mock_indodax_response(start_ts, 10)

    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_data
    mock_session.get.return_value = mock_resp

    to_ts = start_ts + (10 * 3600)

    # 1. First call: Cache miss -> calls HTTP
    df1 = fetch_indodax_ohlcv(
        symbol="BTCIDR",
        tf="60",
        from_ts=start_ts,
        to_ts=to_ts,
        cache_dir=tmp_path,
        session=mock_session,
    )
    assert len(df1) == 10
    assert mock_session.get.call_count == 1
    cache_file = tmp_path / "indodax" / f"BTCIDR_60_{start_ts}_{to_ts}.csv.gz"
    assert cache_file.exists()

    # 2. Second call: Cache hit -> does NOT call HTTP
    mock_session.reset_mock()
    df2 = fetch_indodax_ohlcv(
        symbol="BTCIDR",
        tf="60",
        from_ts=start_ts,
        to_ts=to_ts,
        cache_dir=tmp_path,
        session=mock_session,
    )
    assert len(df2) == 10
    assert mock_session.get.call_count == 0
    pd.testing.assert_frame_equal(df1, df2)


def test_gap_detection_raises_value_error(tmp_path: Path):
    """Verifies that consecutive timestamps with missing hours raise ValueError."""
    start_ts = 1672531200
    # Create 5 bars, but bar 3 is skipped (gap from bar 2 to 4 is 7200s > 3600s)
    bad_data = [
        {"Time": start_ts, "Open": 100, "High": 105, "Low": 95, "Close": 102, "Volume": "1"},
        {"Time": start_ts + 3600, "Open": 102, "High": 108, "Low": 100, "Close": 104, "Volume": "1"},
        {"Time": start_ts + 7200, "Open": 104, "High": 110, "Low": 102, "Close": 107, "Volume": "1"},
        # Skip start_ts + 10800! Next bar is + 14400
        {"Time": start_ts + 14400, "Open": 107, "High": 112, "Low": 105, "Close": 109, "Volume": "1"},
    ]

    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = bad_data
    mock_session.get.return_value = mock_resp

    with pytest.raises(ValueError) as excinfo:
        fetch_indodax_ohlcv(
            symbol="BTCIDR",
            tf="60",
            from_ts=start_ts,
            to_ts=start_ts + 14400,
            cache_dir=tmp_path,
            session=mock_session,
        )
    assert "Data gap detected" in str(excinfo.value)
    assert "missing bar" in str(excinfo.value)


def test_align_indodax_binance_overlap_and_derived_columns():
    """
    Verifies that inner join correctly matches UTC timestamps,
    calculates overlap percentage, and computes hourly returns and dislocation.
    """
    start_ts = 1672531200
    # Indodax: 10 bars (0 to 9)
    indo_records = []
    for i in range(10):
        ts = start_ts + (i * 3600)
        indo_records.append({
            "timestamp_utc": ts,
            "open": 100.0,
            "high": 110.0,
            "low": 90.0,
            "close": 102.0,  # +2.0% return
            "volume": 5.0,
        })
    indo_df = pd.DataFrame(indo_records)

    # Binance: 10 bars, but offset by 2 bars (2 to 11) -> 8 overlapping bars (2 to 9)
    bina_records = []
    for i in range(2, 12):
        ts = start_ts + (i * 3600)
        bina_records.append({
            "timestamp_utc": ts,
            "open": 1000.0,
            "high": 1050.0,
            "low": 980.0,
            "close": 1030.0,  # +3.0% return
            "volume": 50.0,
        })
    bina_df = pd.DataFrame(bina_records)

    aligned = align_indodax_binance(indo_df, bina_df)

    # 8 overlapping rows
    assert len(aligned) == 8
    assert aligned.loc[0, "timestamp_utc"] == start_ts + (2 * 3600)
    assert aligned.loc[7, "timestamp_utc"] == start_ts + (9 * 3600)

    # Verify derived returns:
    # Indo return = (102 - 100) / 100 = +0.02 (+2.0%)
    # Binance return = (1030 - 1000) / 1000 = +0.03 (+3.0%)
    # Dislocation = 0.03 - 0.02 = +0.01 (+1.0% lead)
    assert aligned.loc[0, "indo_return_1h"] == pytest.approx(0.02, rel=1e-6)
    assert aligned.loc[0, "binance_return_1h"] == pytest.approx(0.03, rel=1e-6)
    assert aligned.loc[0, "dislocation_1h"] == pytest.approx(0.01, rel=1e-6)


def test_timezone_utc_consistency(tmp_path: Path):
    """
    Verifies that returned timestamp_utc corresponds strictly to exact UTC hourly boundaries.
    """
    start_ts = 1672531200  # 2023-01-01 00:00:00 UTC
    mock_data = _make_mock_indodax_response(start_ts, 3)

    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_data
    mock_session.get.return_value = mock_resp

    df = fetch_indodax_ohlcv(
        symbol="BTCIDR",
        tf="60",
        from_ts=start_ts,
        to_ts=start_ts + (3 * 3600),
        cache_dir=tmp_path,
        session=mock_session,
    )

    for ts in df["timestamp_utc"]:
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        assert dt.minute == 0
        assert dt.second == 0
