import json
from pathlib import Path


FORBIDDEN = ("paper", "sim", "mock", "canary", "view-only")


def test_dashboard_html_has_no_legacy_labels():
    html = Path("Core/Intelligence/dashboard/index.html").read_text(encoding="utf-8").lower()
    for term in FORBIDDEN:
        assert term not in html


def test_control_plane_payload_has_no_legacy_labels():
    from Core.Intelligence.kibot_dashboard import _build_control_plane_payload

    payload = _build_control_plane_payload()
    focus = {
        "mode": payload.get("mode"),
        "venues": payload.get("venues"),
        "workflow": payload.get("workflow"),
        "gates": payload.get("gates"),
        "runtime": payload.get("runtime"),
    }
    blob = json.dumps(focus, default=str).lower()
    for term in FORBIDDEN:
        assert term not in blob
