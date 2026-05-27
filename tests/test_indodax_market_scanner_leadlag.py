import asyncio
from unittest.mock import AsyncMock

from Core.Scanner import indodax_market_scanner as scanner_module
from Core.Scanner import indodax_binance_leadlag_scanner as leadlag_module
from Core.Scanner.indodax_market_scanner import IndodaxMarketScanner


def test_indodax_market_scanner_merges_leadlag_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(scanner_module, "STATE_FILE", tmp_path / "indodax_scanner_state.json")
    monkeypatch.setattr(leadlag_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(leadlag_module, "STATE_FILE", tmp_path / "indodax_binance_leadlag_scanner.json")

    scanner = IndodaxMarketScanner()
    scanner._fetch_pair_metadata = lambda: {}
    scanner.scanner.fetch_all_tickers = lambda: {
        "btc_idr": {
            "last": 960_600_000.0,
            "buy": 960_500_000.0,
            "sell": 960_900_000.0,
            "high": 970_000_000.0,
            "low": 950_000_000.0,
            "vol_idr": 220_000_000.0,
        }
    }
    scanner.scanner.detect_pump = lambda pair, ticker: None
    scanner.leadlag_scanner.scan = AsyncMock(return_value={
            "scan_mode": "BINANCE_TO_INDODAX_LEADLAG",
            "source_status": "OK",
            "pairs_checked": 1,
            "binance_pairs_checked": 1,
            "leadlag_candidates": [
                {
                    "symbol": "BTC/IDR",
                    "pair": "btc_idr",
                    "binance_symbol": "BTCUSDT",
                    "leader_symbol": "BTCUSDT",
                    "last_price": 960_600_000.0,
                    "leader_price": 61_200.0,
                    "leader_change_pct": 2.0,
                    "follower_change_pct": 0.1,
                    "leadlag_gap_pct": 1.9,
                    "leadlag_lag_seconds": 4.0,
                    "leadlag_score": 21.0,
                    "entry_score": 65.0,
                    "confidence": 0.92,
                    "expected_net_pct": 1.2,
                    "volume_24h_idr": 220_000_000.0,
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
            ],
            "leadlag_watchlist": [],
            "rejected_candidates": [],
            "top_candidate": {"symbol": "BTC/IDR", "entry_score": 65.0},
            "why_empty": "",
        })

    state = asyncio.run(scanner.scan())
    assert state["leadlag_candidates"]
    assert state["leadlag_source_status"] == "OK"
    assert state["best_candidate"]["symbol"] == "BTC/IDR"
    assert state["best_candidate"]["source_pool"] == "leadlag_candidates"


def test_indodax_market_scanner_blocks_maintenance_leadlag_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(scanner_module, "STATE_FILE", tmp_path / "indodax_scanner_state.json")

    scanner = IndodaxMarketScanner()
    scanner._fetch_pair_metadata = lambda: {
        "pond_idr": {
            "is_maintenance": 1,
            "is_market_suspended": 0,
            "trade_min_base_currency": 10000,
            "trade_min_traded_currency": 90,
        }
    }
    scanner.scanner.fetch_all_tickers = lambda: {
        "pond_idr": {
            "last": 112.0,
            "buy": 111.0,
            "sell": 112.0,
            "high": 160.0,
            "low": 48.0,
            "vol_idr": 10_000_000_000.0,
        }
    }
    scanner.scanner.detect_pump = lambda pair, ticker: None
    scanner.leadlag_scanner.scan = AsyncMock(return_value={
        "scan_mode": "BINANCE_TO_INDODAX_LEADLAG",
        "source_status": "OK",
        "pairs_checked": 1,
        "binance_pairs_checked": 1,
        "leadlag_candidates": [
            {
                "symbol": "POND/IDR",
                "pair": "pond_idr",
                "last_price": 112.0,
                "entry_score": 99.0,
                "volume_24h_idr": 10_000_000_000.0,
                "route_status": "EXECUTABLE",
                "recommended_action": "ENTER",
                "source_proof": {
                    "source_type": "REAL_EXCHANGE",
                    "source_name": "Indodax",
                    "source_url_or_endpoint": "https://indodax.com/api/summaries",
                    "raw_id": "pond_idr",
                    "symbol": "POND/IDR",
                    "address_or_mint": "pond_idr",
                    "chain": "idr",
                    "proof_ok": True,
                },
            }
        ],
        "leadlag_watchlist": [],
        "rejected_candidates": [],
        "top_candidate": {},
        "why_empty": "",
    })

    state = asyncio.run(scanner.scan())

    assert state["leadlag_candidates"][0]["route_status"] == "BLOCKED_WITH_REASON"
    assert state["leadlag_candidates"][0]["recommended_action"] == "REJECT"
    assert "maintenance" in state["leadlag_candidates"][0]["reason"]
