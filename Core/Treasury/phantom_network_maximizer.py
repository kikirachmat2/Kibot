from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "phantom_network_maximizer.json"


def write_phantom_network_maximizer(payload: Dict[str, Any]) -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    resolved = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "best_route": "",
        "best_candidate": {},
        "executable_routes": [],
        "blocked_routes": {},
        "recommended_action": "SCAN_NEXT",
        "reason": "",
    }
    resolved.update(payload or {})
    STATE_FILE.write_text(json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")
    return resolved

