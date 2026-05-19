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
