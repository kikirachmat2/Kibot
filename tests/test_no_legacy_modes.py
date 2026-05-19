import json
import re
from pathlib import Path


FORBIDDEN = ("paper", "sim", "mock", "canary", "view-only")
FORBIDDEN_PATTERNS = (
    re.compile(r"\bpaper\b"),
    re.compile(r"\bsim\b"),
    re.compile(r"\bmock\b"),
    re.compile(r"\bcanary\b"),
    re.compile(r"view-only"),
)


def test_dashboard_html_has_no_legacy_labels():
    html = Path("Core/Intelligence/dashboard/index.html").read_text(encoding="utf-8").lower()
    for pattern in FORBIDDEN_PATTERNS:
        assert not pattern.search(html)


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
    for pattern in FORBIDDEN_PATTERNS:
        assert not pattern.search(blob)
