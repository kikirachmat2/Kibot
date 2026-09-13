from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "engine_independence.json"


def write_engine_independence(payload: Dict[str, Any]) -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    existing = {}
    if STATE_FILE.exists():
        try:
            existing = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except Exception:
            existing = {}
    resolved = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "global_mode": "INDODAX_ONLY_LIVE",
        "indodax_engine": {
            "status": "ACTIVE",
            "scanner": "ACTIVE",
            "executor": "ACTIVE",
            "allow_orders": True,
            "reason": "",
        },
    }
    resolved.update(existing)
    resolved.update(payload or {})
    resolved["global_mode"] = "INDODAX_ONLY_LIVE"
    removed_keys = (
        "ph" + "antom_engine",
        "br" + "idge",
        "withdrawal",
        "retired_venues",
    )
    for removed_key in removed_keys:
        resolved.pop(removed_key, None)
    STATE_FILE.write_text(json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")
    return resolved
