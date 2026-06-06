import json

from scripts import final_server_claim as claim


def test_final_server_claim_writes_state(tmp_path, monkeypatch):
    monkeypatch.setattr(claim, "STATE", tmp_path)
    monkeypatch.setattr(claim, "CLAIM_FILE", tmp_path / "final_server_claim.json")
    monkeypatch.setattr(claim, "build_indodax_target_board", lambda: {"top_targets": [{"rank": 1}]})
    monkeypatch.setattr(claim, "build_phantom_target_board", lambda: {"top_targets": [{"rank": 1}]})
    monkeypatch.setattr(claim.ScannerExecutorContract, "write_contract_state", lambda self: {"routes": []})
    monkeypatch.setattr(claim, "write_scanner_health", lambda contract=None: {"status": "OK"})
    monkeypatch.setattr(claim, "write_server_telemetry", lambda payload=None: {"cpu": 1.0})
    (tmp_path / "engine_independence.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    (tmp_path / "capital_governor.json").write_text(json.dumps({"status": "RECONCILED"}), encoding="utf-8")
    (tmp_path / "indodax_scanner_state.json").write_text(json.dumps({"source_status": "OK", "pairs_checked": 1, "gainers_24h": [{"symbol": "AAA/IDR", "pair": "aaa_idr", "source_proof": {"proof_ok": True}}]}), encoding="utf-8")
    (tmp_path / "indodax_no_idle.json").write_text(json.dumps({"posture": "ACTIVE_SEARCHING"}), encoding="utf-8")
    (tmp_path / "phantom_treasury.json").write_text(json.dumps({"buckets": {"swap_idr": 1000, "base_idrx_idr": 1000}}), encoding="utf-8")
    (tmp_path / "phantom_capital_mover.json").write_text(json.dumps({"bridge": "ON", "withdrawal": "ON"}), encoding="utf-8")
    (tmp_path / "phantom_network_maximizer.json").write_text(json.dumps({"best_route": "solana_jupiter"}), encoding="utf-8")
    (tmp_path / "deadline_profit_enforcer.json").write_text(json.dumps({"stage": "NORMAL"}), encoding="utf-8")
    (tmp_path / "scanner_executor_contract.json").write_text(json.dumps({"routes": {"indodax": {}}, "source_proof_count": 1}), encoding="utf-8")
    (tmp_path / "scanner_health.json").write_text(json.dumps({"status": "OK"}), encoding="utf-8")
    (tmp_path / "server_telemetry.json").write_text(json.dumps({"cpu": 1.0}), encoding="utf-8")
    (tmp_path / "ai_strategy_review.json").write_text(json.dumps({"role": "REVIEW_AND_ADAPTATION_ONLY"}), encoding="utf-8")
    (tmp_path / "indodax_top_targets.json").write_text(json.dumps({"top_targets": [{"rank": 1}]}), encoding="utf-8")
    (tmp_path / "phantom_top_targets.json").write_text(json.dumps({"top_targets": [{"rank": 1}]}), encoding="utf-8")
    result = claim.build_final_claim()
    assert result["top_targets"]["indodax_count"] == 1
    assert result["top_targets"]["phantom_count"] == 0
    assert result["phantom_engine"]["status"] == "REMOVED_BY_OPERATOR"
