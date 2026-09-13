from __future__ import annotations

from pathlib import Path


def test_dashboard_no_legacy_visible_strings():
    index_html = Path("Core/Intelligence/dashboard/index.html").read_text(encoding="utf-8")
    live_js = Path("Core/Intelligence/dashboard/live.js").read_text(encoding="utf-8")
    combined = "\n".join([index_html, live_js])
    for needle in ("CONTROLLED-LIVE", "Controlled Live", "Indodax Shadow", "VIEW ONLY", "Live trading OFF"):
        assert needle not in combined

