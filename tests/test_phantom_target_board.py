import json

from Core.Decision import phantom_target_board as board


def test_phantom_target_board_builds(tmp_path, monkeypatch):
    monkeypatch.setattr(board, "STATE_DIR", tmp_path)
    monkeypatch.setattr(board, "STATE_FILE", tmp_path / "phantom_top_targets.json")
    (tmp_path / "phantom_treasury.json").write_text(json.dumps({"buckets": {"swap_idr": 1000, "base_idrx_idr": 2000}}), encoding="utf-8")
    (tmp_path / "phantom_capital_mover.json").write_text(json.dumps({"bridge": "OFF", "withdrawal": "OFF"}), encoding="utf-8")
    (tmp_path / "phantom_network_maximizer.json").write_text(json.dumps({"best_route": "solana_jupiter"}), encoding="utf-8")
    (tmp_path / "scanner_executor_contract.json").write_text(json.dumps({"routes": {"solana": {"status": "LIVE_READY"}}, "source_proof_count": 1}), encoding="utf-8")
    (tmp_path / "web3_opportunities.json").write_text(json.dumps({"best_opportunities": [{"route": "solana_jupiter", "symbol": "SOL", "quote_ok": True, "exit_route_ok": True, "source_proof_ok": True, "executor_status": "EXECUTABLE", "wave_score": 9}]}), encoding="utf-8")
    result = board.build_phantom_target_board()
    assert result["top_targets"]
    assert result["top_targets"][0]["route"] == "solana_jupiter"
