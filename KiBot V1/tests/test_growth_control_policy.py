from __future__ import annotations

import json
from pathlib import Path


def test_growth_control_policy_exists() -> None:
    data = json.loads(Path("config/growth_control_policy.json").read_text(encoding="utf-8"))
    assert data["require_closed_round_trip_for_growth_claim"] is True

