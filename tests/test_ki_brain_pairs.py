"""Unit test for Indodax pairs cache parser in Core/ki_brain.py."""

import pytest
from Core.ki_brain import BrainManager


def test_indodax_pairs_cache_parsing():
    mock_indodax_api_data = [
        # Standard Indodax API format (base_currency = idr, traded_currency = btc)
        {
            "id": "btcidr",
            "symbol": "BTCIDR",
            "base_currency": "idr",
            "traded_currency": "btc",
            "ticker_id": "btc_idr",
        },
        # Indodax API format for altcoin
        {
            "id": "edenidr",
            "symbol": "EDENIDR",
            "base_currency": "idr",
            "traded_currency": "eden",
            "ticker_id": "eden_idr",
        },
        # USDT pair (should be ignored for IDR cache)
        {
            "id": "btcusdt",
            "symbol": "BTCUSDT",
            "base_currency": "usdt",
            "traded_currency": "btc",
            "ticker_id": "btc_usdt",
        },
        # Alternate standard schema (traded_currency = eth, quote_currency = idr)
        {
            "id": "ethidr",
            "symbol": "ETHIDR",
            "traded_currency": "eth",
            "quote_currency": "idr",
            "ticker_id": "eth_idr",
        },
    ]

    cache = BrainManager._parse_indodax_pairs_payload(mock_indodax_api_data)

    assert "BTC" in cache
    assert cache["BTC"] == "btc_idr"
    assert "EDEN" in cache
    assert cache["EDEN"] == "eden_idr"
    assert "ETH" in cache
    assert cache["ETH"] == "eth_idr"

    # USDT pair should NOT be in IDR cache
    assert "BTCUSDT" not in cache
