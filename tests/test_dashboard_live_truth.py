from __future__ import annotations

from pathlib import Path


def test_dashboard_mentions_live_truth():
    text = Path("Core/Intelligence/kibot_dashboard.py").read_text(encoding="utf-8")
    assert "live_truth" in text
    assert "_load_live_truth" in text

