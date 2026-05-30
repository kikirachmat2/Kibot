from __future__ import annotations

import json
from pathlib import Path

from Core.Treasury.live_truth_manager import build_live_truth, load_live_truth


def test_live_truth_manager_writes_schema():
    payload = build_live_truth()
    assert payload["runtime_mode"] == "LIVE_ONLY"
    assert "updated_at" in payload
    assert "indodax" in payload and "phantom" in payload
    state = Path("state/live_truth.json")
    assert state.exists()
    loaded = load_live_truth()
    assert isinstance(loaded, dict)
    assert loaded.get("runtime_mode") == "LIVE_ONLY"
    json.loads(state.read_text(encoding="utf-8"))

