from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from Core.Support.ki_config import KiConfig

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
    phantom_engine = {
        "status": "REMOVED_BY_OPERATOR",
        "scanner": "OFF",
        "executor": "OFF",
        "allow_orders": False,
        "reason": "operator_removed_compromised_wallet_use_indodax_only",
    } if KiConfig.INDODAX_ONLY else {
        "status": "ACTIVE",
        "scanner": "ACTIVE",
        "executor": "ACTIVE",
        "allow_orders": True,
        "reason": "",
    }
    resolved = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "global_mode": "INDODAX_ONLY_LIVE" if KiConfig.INDODAX_ONLY else "CONTROLLED_LIVE_INDEPENDENT_ENGINES",
        "indodax_engine": {
            "status": "ACTIVE",
            "scanner": "ACTIVE",
            "executor": "ACTIVE",
            "allow_orders": True,
            "reason": "",
        },
        "phantom_engine": phantom_engine,
        "bridge": "OFF" if KiConfig.INDODAX_ONLY else "ON",
        "withdrawal": "OFF" if KiConfig.INDODAX_ONLY else "ON",
        "retired_venues": {"phantom": "REMOVED_BY_OPERATOR"} if KiConfig.INDODAX_ONLY else {},
    }
    resolved.update(existing)
    resolved.update(payload or {})
    if KiConfig.INDODAX_ONLY:
        resolved["global_mode"] = "INDODAX_ONLY_LIVE"
        resolved["bridge"] = "OFF"
        resolved["withdrawal"] = "OFF"
        resolved["phantom_engine"] = phantom_engine
        resolved["retired_venues"] = {"phantom": "REMOVED_BY_OPERATOR"}
    STATE_FILE.write_text(json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")
    return resolved
