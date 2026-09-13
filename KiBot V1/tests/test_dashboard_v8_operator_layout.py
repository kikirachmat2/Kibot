from pathlib import Path


def test_dashboard_v8_operator_layout():
    html = Path("Core/Intelligence/dashboard/index.html").read_text(encoding="utf-8")
    for needle in ("KiBot Live Command Center", "section-nav", "Overview", "Workflow", "Venues", "AI System", "Orders", "Logs", "Debug", "status-banner", "page-container"):
        assert needle in html
