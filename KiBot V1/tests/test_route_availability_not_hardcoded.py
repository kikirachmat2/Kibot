from __future__ import annotations

import json
from pathlib import Path


def test_route_availability_not_hardcoded_true():
    paths = [
        Path("state/indodax_scanner_state.json"),
    ]
    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text())
        candidates = payload.get("candidates") if isinstance(payload, dict) else []
        if not isinstance(candidates, list):
            continue
        for cand in candidates:
            if isinstance(cand, dict):
                assert cand.get("route_availability") is not True
