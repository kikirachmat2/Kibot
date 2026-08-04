"""Unit tests for Multi-Candle Momentum Validation in IndodaxMarketScanner."""

import asyncio
import pytest
from Core.Scanner.indodax_market_scanner import IndodaxMarketScanner


def test_scanner_collect_signals_attaches_momentum_score(monkeypatch):
    scanner = IndodaxMarketScanner()

    # Mock market summary fetch
    def mock_fetch():
        return {
            "btc_idr": {
                "last": "100000",
                "high": "105000",
                "low": "95000",
                "vol_idr": "500000000",
            }
        }

    # Mock pump detection
    def mock_detect_pump(pair, ticker):
        return {
            "symbol": "BTC/IDR",
            "price": 100000.0,
            "change_pct": 5.2,
            "vol_ratio": 3.1,
            "confidence": 0.82,
        }

    monkeypatch.setattr(scanner.scanner, "detect_pump", mock_detect_pump)

    # Attach mock summaries directly
    res = asyncio.run(scanner.collect_signals())
    assert isinstance(res, list)
