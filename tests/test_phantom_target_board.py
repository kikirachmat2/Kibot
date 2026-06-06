import json

from Core.Decision import phantom_target_board as board


def test_phantom_target_board_builds(tmp_path, monkeypatch):
    monkeypatch.setattr(board, "STATE_DIR", tmp_path)
    monkeypatch.setattr(board, "STATE_FILE", tmp_path / "phantom_top_targets.json")
    (tmp_path / "phantom_treasury.json").write_text(json.dumps({"buckets": {"swap_idr": 1000, "base_idrx_idr": 2000}}), encoding="utf-8")
    (tmp_path / "phantom_capital_mover.json").write_text(json.dumps({"bridge": "ON", "withdrawal": "ON"}), encoding="utf-8")
    (tmp_path / "phantom_network_maximizer.json").write_text(json.dumps({"best_route": "solana_jupiter"}), encoding="utf-8")
    (tmp_path / "scanner_executor_contract.json").write_text(json.dumps({"routes": {"solana": {"status": "LIVE_READY"}}, "source_proof_count": 1}), encoding="utf-8")
    (tmp_path / "web3_opportunities.json").write_text(json.dumps({"best_opportunities": [{"route": "solana_jupiter", "symbol": "SOL", "quote_ok": True, "exit_route_ok": True, "source_proof_ok": True, "executor_status": "EXECUTABLE", "wave_score": 9}]}), encoding="utf-8")
    result = board.build_phantom_target_board()
    assert result["status"] == "REMOVED_BY_OPERATOR"
    assert result["top_targets"] == []


def test_phantom_target_board_does_not_enter_without_quote_or_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(board, "STATE_DIR", tmp_path)
    monkeypatch.setattr(board, "STATE_FILE", tmp_path / "phantom_top_targets.json")
    (tmp_path / "phantom_treasury.json").write_text(
        json.dumps({"buckets": {"swap_idr": 1000}, "sol_balance": 0.01}),
        encoding="utf-8",
    )
    (tmp_path / "phantom_capital_mover.json").write_text("{}", encoding="utf-8")
    (tmp_path / "phantom_network_maximizer.json").write_text("{}", encoding="utf-8")
    (tmp_path / "scanner_executor_contract.json").write_text(
        json.dumps(
            {
                "routes": [
                    {
                        "route": "solana_jupiter",
                        "can_scan": True,
                        "can_quote": True,
                        "can_execute": True,
                        "can_exit": True,
                        "status": "LIVE_READY",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "web3_opportunities.json").write_text(
        json.dumps(
            {
                "best_opportunities": [
                    {
                        "route": "solana_jupiter",
                        "symbol": "SOL",
                        "quote_ok": False,
                        "exit_route_ok": False,
                        "source_proof_ok": True,
                        "executor_status": "EXECUTABLE",
                        "wave_score": 90,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = board.build_phantom_target_board()

    assert result["status"] == "REMOVED_BY_OPERATOR"
    assert result["top_targets"] == []
    assert result["why_empty"] == "operator_removed_compromised_wallet_use_indodax_only"
