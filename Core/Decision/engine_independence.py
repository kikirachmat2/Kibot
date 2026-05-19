from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "engine_independence.json"


def write_engine_independence(payload: Dict[str, Any]) -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    resolved = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "global_mode": "CONTROLLED_LIVE_INDEPENDENT_ENGINES",
        "indodax_engine": {
            "status": "ACTIVE",
            "scanner": "ACTIVE",
            "executor": "ACTIVE",
            "allow_orders": True,
            "reason": "",
        },
        "phantom_engine": {
            "status": "ACTIVE",
            "scanner": "ACTIVE",
            "executor": "ACTIVE",
            "allow_orders": True,
            "reason": "",
        },
        "bridge": "OFF",
        "withdrawal": "OFF",
    }
    resolved.update(payload or {})
    STATE_FILE.write_text(json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")
    return resolved

