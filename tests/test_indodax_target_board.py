import json

from Core.Decision import indodax_target_board as board


def test_indodax_target_board_builds(tmp_path, monkeypatch):
    monkeypatch.setattr(board, "STATE_DIR", tmp_path)
    monkeypatch.setattr(board, "STATE_FILE", tmp_path / "indodax_top_targets.json")
    scan = {
        "source_status": "OK",
        "pairs_checked": 2,
        "gainers_24h": [
            {
                "symbol": "AAA/IDR",
                "pair": "aaa_idr",
                "change_24h_pct": 12.5,
                "volume_idr": 250_000_000,
                "last_price": 1000,
                "source_proof": {
                    "source_type": "REAL_EXCHANGE",
                    "source_name": "Indodax",
                    "source_url_or_endpoint": "https://indodax.com/api/summaries",
                    "raw_id": "aaa_idr",
                    "symbol": "AAA/IDR",
                    "address_or_mint": "aaa_idr",
                    "chain": "rupiah",
                    "proof_ok": True,
                },
            }
        ],
        "rejected_candidates": [],
        "no_data_reason": "",
    }
    (tmp_path / "indodax_scanner_state.json").write_text(json.dumps(scan), encoding="utf-8")
    result = board.build_indodax_target_board()
    assert result["top_targets"]
    assert result["top_targets"][0]["symbol"] == "AAA/IDR"


def test_indodax_target_board_prioritizes_leadlag_pool(tmp_path, monkeypatch):
    monkeypatch.setattr(board, "STATE_DIR", tmp_path)
    monkeypatch.setattr(board, "STATE_FILE", tmp_path / "indodax_top_targets.json")
    scan = {
        "source_status": "OK",
        "pairs_checked": 2,
        "leadlag_candidates": [
            {
                "symbol": "BTC/IDR",
                "pair": "btc_idr",
                "binance_symbol": "BTCUSDT",
                "leader_symbol": "BTCUSDT",
                "change_24h_pct": 2.0,
                "leader_change_pct": 2.0,
                "follower_change_pct": 0.1,
                "leadlag_gap_pct": 1.9,
                "leadlag_lag_seconds": 4.0,
                "leadlag_score": 18.0,
                "entry_score": 42.0,
                "confidence": 0.91,
                "expected_net_pct": 1.2,
                "volume_24h_idr": 120_000_000,
                "spread_pct": 0.12,
                "last_price": 960_000_000,
                "route_status": "EXECUTABLE",
                "recommended_action": "ENTER",
                "reason": "",
                "source_proof": {
                    "source_type": "REAL_EXCHANGE",
                    "source_name": "Indodax",
                    "source_url_or_endpoint": "https://indodax.com/api/summaries",
                    "fetched_at": "2026-05-21T00:00:00+00:00",
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
                    "fetched_at": "2026-05-21T00:00:00+00:00",
                    "raw_id": "BTCUSDT",
                    "symbol": "BTCUSDT",
                    "address_or_mint": "BTCUSDT",
                    "chain": "usdt",
                    "proof_ok": True,
                },
            }
        ],
        "gainers_24h": [],
        "volume_leaders": [],
        "rejected_candidates": [],
        "no_data_reason": "",
    }
    (tmp_path / "indodax_scanner_state.json").write_text(json.dumps(scan), encoding="utf-8")
    result = board.build_indodax_target_board()
    assert result["source_breakdown"]["leadlag_candidates"]["count"] == 1
    assert result["top_targets"]
    assert result["top_targets"][0]["source_pool"] == "leadlag_candidates"
    assert result["top_targets"][0]["recommended_action"] == "ENTER"


def test_indodax_target_board_blocks_maintenance_pair(tmp_path, monkeypatch):
    monkeypatch.setattr(board, "STATE_DIR", tmp_path)
    monkeypatch.setattr(board, "STATE_FILE", tmp_path / "indodax_top_targets.json")
    scan = {
        "source_status": "OK",
        "pairs_checked": 1,
        "brutal_momentum_candidates": [
            {
                "symbol": "POND/IDR",
                "pair": "pond_idr",
                "change_24h_pct": 175.0,
                "volume_idr": 10_000_000_000,
                "last_price": 112.0,
                "entry_score": 999,
                "route_status": "EXECUTABLE",
                "is_maintenance": True,
                "is_market_suspended": False,
                "source_proof": {
                    "source_type": "REAL_EXCHANGE",
                    "source_name": "Indodax",
                    "source_url_or_endpoint": "https://indodax.com/api/summaries",
                    "raw_id": "pond_idr",
                    "symbol": "POND/IDR",
                    "address_or_mint": "pond_idr",
                    "chain": "rupiah",
                    "proof_ok": True,
                },
            }
        ],
    }
    (tmp_path / "indodax_scanner_state.json").write_text(json.dumps(scan), encoding="utf-8")

    result = board.build_indodax_target_board()

    assert result["top_targets"][0]["symbol"] == "POND/IDR"
    assert result["top_targets"][0]["route_status"] == "BLOCKED_WITH_REASON"
    assert result["top_targets"][0]["recommended_action"] == "REJECT"
    assert "maintenance" in result["top_targets"][0]["reason"]
