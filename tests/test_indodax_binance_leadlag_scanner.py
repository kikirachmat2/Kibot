import asyncio
import json
from unittest.mock import AsyncMock

from Core.Scanner import indodax_binance_leadlag_scanner as leadlag_module
from Core.Scanner.indodax_binance_leadlag_scanner import IndodaxBinanceLeadLagScanner
from Core.Scanner.source_proof import SourceProof


def test_indodax_binance_leadlag_scanner_builds_enter_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(leadlag_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(leadlag_module, "STATE_FILE", tmp_path / "indodax_binance_leadlag_scanner.json")

    scanner = IndodaxBinanceLeadLagScanner()
    scanner.lookback_sec = 12

    first_indodax = {
        "btc_idr": {
            "pair": "btc_idr",
            "symbol": "BTC/IDR",
            "last": 960_000_000.0,
            "buy": 959_900_000.0,
            "sell": 960_100_000.0,
            "vol_idr": 200_000_000.0,
        }
    }
    second_indodax = {
        "btc_idr": {
            "pair": "btc_idr",
            "symbol": "BTC/IDR",
            "last": 960_600_000.0,
            "buy": 960_500_000.0,
            "sell": 960_900_000.0,
            "vol_idr": 220_000_000.0,
        }
    }
    first_binance = {
        "BTCUSDT": {
            "symbol": "BTCUSDT",
            "lastPrice": 60_000.0,
            "quoteVolume": 10_000_000.0,
            "priceChangePercent": 0.0,
            "highPrice": 60_000.0,
            "lowPrice": 59_500.0,
        }
    }
    second_binance = {
        "BTCUSDT": {
            "symbol": "BTCUSDT",
            "lastPrice": 61_200.0,
            "quoteVolume": 12_000_000.0,
            "priceChangePercent": 2.0,
            "highPrice": 61_200.0,
            "lowPrice": 59_500.0,
        }
    }

    state_1 = asyncio.run(scanner.scan(indodax_tickers=first_indodax, binance_tickers=first_binance))
    assert state_1["leadlag_candidates"] == []

    state_2 = asyncio.run(scanner.scan(indodax_tickers=second_indodax, binance_tickers=second_binance))
    assert state_2["scan_mode"] == "BINANCE_TO_INDODAX_LEADLAG"
    assert state_2["leadlag_candidates"]
    top = state_2["top_candidate"]
    assert top["symbol"] == "BTC/IDR"
    assert top["route_status"] == "EXECUTABLE"
    assert top["recommended_action"] in {"ENTER", "WATCH"}
    assert SourceProof.validate(top["source_proof"])
    assert SourceProof.validate(top["leader_source_proof"])
    assert top["binance_symbol"] == "BTCUSDT"
    assert top["leadlag_gap_pct"] > 0
    assert top["leadlag_lag_seconds"] >= 0

    persisted = json.loads((tmp_path / "indodax_binance_leadlag_scanner.json").read_text(encoding="utf-8"))
    assert persisted["scan_mode"] == "BINANCE_TO_INDODAX_LEADLAG"
    assert persisted["leadlag_candidates"]


def test_indodax_binance_leadlag_collect_signals_only_enter(monkeypatch, tmp_path):
    monkeypatch.setattr(leadlag_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(leadlag_module, "STATE_FILE", tmp_path / "indodax_binance_leadlag_scanner.json")

    scanner = IndodaxBinanceLeadLagScanner()
    scanner.lookback_sec = 12

    signal = {
        "rank": 1,
        "symbol": "BTC/IDR",
        "pair": "BTC_IDR",
        "binance_symbol": "BTCUSDT",
        "leader_symbol": "BTCUSDT",
        "price": 960_600_000.0,
        "leader_price": 61_200.0,
        "follower_price": 960_600_000.0,
        "leader_change_pct": 2.0,
        "follower_change_pct": 0.1,
        "leadlag_gap_pct": 1.9,
        "leadlag_lag_seconds": 4.0,
        "leadlag_window_sec": 12.0,
        "leadlag_score": 21.0,
        "entry_score": 45.0,
        "confidence": 0.92,
        "expected_net_pct": 1.2,
        "volume_24h_idr": 220_000_000.0,
        "leader_quote_volume": 12_000_000.0,
        "spread_pct": 0.1,
        "route_status": "EXECUTABLE",
        "recommended_action": "ENTER",
        "reason": "",
        "source_proof": {
            "source_type": "REAL_EXCHANGE",
            "source_name": "Indodax",
            "source_url_or_endpoint": "https://indodax.com/api/summaries",
            "raw_id": "btc_idr",
            "symbol": "BTC/IDR",
            "address_or_mint": "btc_idr",
            "chain": "idr",
            "proof_ok": True,
        },
        "leader_source_proof": {
            "source_type": "REAL_API",
            "source_name": "Binance",
            "source_url_or_endpoint": "https://api.binance.com/api/v3/ticker/24hr",
            "raw_id": "BTCUSDT",
            "symbol": "BTCUSDT",
            "address_or_mint": "BTCUSDT",
            "chain": "usdt",
            "proof_ok": True,
        },
    }
    monkeypatch.setattr(scanner, "scan", AsyncMock(return_value={"leadlag_candidates": [signal]}))
    result = asyncio.run(scanner.collect_signals())
    assert result["signals"]
    assert result["signals"][0]["leadlag_pass"] is True
