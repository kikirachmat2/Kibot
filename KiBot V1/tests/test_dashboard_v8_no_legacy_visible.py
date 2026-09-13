from pathlib import Path


def test_dashboard_v8_no_legacy_visible():
    html = Path("Core/Intelligence/dashboard/index.html").read_text(encoding="utf-8")
    for needle in ("CONTROLLED-LIVE", "Project Info", "Blocked Reason", "Indodax Shadow", "VIEW ONLY", "Live trading OFF"):
        assert needle not in html
