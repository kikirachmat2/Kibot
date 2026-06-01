from __future__ import annotations

import json
from pathlib import Path

from tests._script_loader import load_script_module


def test_target_freshness_audit_fresh(tmp_path, monkeypatch):
    mod = load_script_module("scripts/audit_target_freshness.py", "audit_target_freshness")
    monkeypatch.setattr(mod, "STATE_DIR", tmp_path)
    monkeypatch.setattr(mod, "OUT_FILE", tmp_path / "target_freshness_audit.json")
    monkeypatch.setattr(mod, "HISTORY_FILE", tmp_path / "target_freshness_history.json")
    (tmp_path / "indodax_top_targets.json").write_text(json.dumps({"updated_at": "2026-06-02T00:00:00+00:00", "top_targets": [{"symbol": "AAA/IDR"}]}), encoding="utf-8")
    (tmp_path / "phantom_top_targets.json").write_text(json.dumps({"updated_at": "2026-06-02T00:00:00+00:00", "top_targets": [{"symbol": "BBB"}]}), encoding="utf-8")
    (tmp_path / "target_board_runtime.json").write_text(json.dumps({"updated_at": "2026-06-02T00:00:00Z"}), encoding="utf-8")
    (tmp_path / "candidate_decisions.jsonl").write_text(json.dumps({"updated_at": "2026-06-02T00:00:00Z"}) + "\n", encoding="utf-8")

    payload = mod.build_target_freshness_audit()
    assert payload["status"] == "FRESH"
    assert "indodax_target_age_s" in payload
    assert "phantom_target_age_s" in payload
    assert payload["top_targets_changed_last_30m"] is True
