"""
Unit tests for KiBot V2 Universe Scanner.
Runs offline using mock responses.
"""
from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest

from backtest.universe_scanner import (
    fetch_all_indodax_pairs,
    fetch_all_binance_usdt_pairs,
    build_pair_mapping,
    compute_liquidity_metrics,
    select_tradable_universe,
)


def test_fetch_all_indodax_pairs():
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"id": "btc_idr", "traded_currency": "idr"},
        {"id": "eth_idr", "traded_currency": "idr"},
        {"id": "sol_idr", "traded_currency": "idr"},
        {"id": "btc_usdt", "traded_currency": "usdt"},  # non-IDR
    ]
    mock_session.get.return_value = mock_resp

    pairs = fetch_all_indodax_pairs(session=mock_session)
    assert pairs == ["BTCIDR", "ETHIDR", "SOLIDR"]


def test_build_pair_mapping():
    indodax_pairs = ["BTCIDR", "ETHIDR", "SOLIDR", "XYZIDR"]
    binance_pairs = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}

    mapping = build_pair_mapping(indodax_pairs, binance_pairs)
    assert mapping["BTCIDR"] == "BTCUSDT"
    assert mapping["ETHIDR"] == "ETHUSDT"
    assert mapping["SOLIDR"] == "SOLUSDT"
    assert mapping["XYZIDR"] is None


def test_compute_liquidity_metrics():
    snap = {
        "vol_idr": "50000000",
        "buy": "10000",
        "sell": "10050",  # spread = 0.5%
    }
    metrics = compute_liquidity_metrics("BTCIDR", snap)
    assert metrics["avg_daily_volume_idr"] == 50_000_000.0
    assert metrics["avg_spread_pct"] == 0.5
    assert metrics["depth_2pct_idr"] == 500_000.0


def test_select_tradable_universe(tmp_path: Path):
    mock_indodax_pairs = ["BTCIDR", "ETHIDR", "LOWVOLIDR", "WIDESPREADIDR", "USDTIDR"]
    mock_binance_pairs = {"BTCUSDT", "ETHUSDT"}
    mock_tickers = {
        "BTCIDR": {"vol_idr": "100000000", "buy": "1000", "sell": "1002"},  # 0.2% spread -> pass
        "ETHIDR": {"vol_idr": "20000000", "buy": "100", "sell": "100.5"},   # 0.5% spread -> pass
        "LOWVOLIDR": {"vol_idr": "5000000", "buy": "10", "sell": "10.01"},   # low vol -> fail
        "WIDESPREADIDR": {"vol_idr": "50000000", "buy": "10", "sell": "10.2"}, # 2.0% spread -> fail
        "USDTIDR": {"vol_idr": "500000000", "buy": "16000", "sell": "16001"}, # stable -> excluded
    }

    with patch("backtest.universe_scanner.fetch_all_indodax_pairs", return_value=mock_indodax_pairs), \
         patch("backtest.universe_scanner.fetch_all_binance_usdt_pairs", return_value=mock_binance_pairs), \
         patch("backtest.universe_scanner.fetch_indodax_ticker_snapshots", return_value=mock_tickers):

        qual = select_tradable_universe(
            min_volume_idr=10_000_000.0,
            max_spread_pct=0.80,
            exclude_stables=True,
            cache_dir=tmp_path,
            force_refresh=True,
        )

        pairs = [q["pair"] for q in qual]
        assert "BTCIDR" in pairs
        assert "ETHIDR" in pairs
        assert "LOWVOLIDR" not in pairs
        assert "WIDESPREADIDR" not in pairs
        assert "USDTIDR" not in pairs

        # Verify caching
        assert (tmp_path / "universe_cache.json").exists()
