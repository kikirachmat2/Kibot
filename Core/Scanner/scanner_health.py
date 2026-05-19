from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "scanner_health.json"


def build_scanner_health(contract: Dict[str, Any] | None = None) -> Dict[str, Any]:
    contract = contract or {}
    routes = contract.get("routes") if isinstance(contract, dict) else {}
    route_count = len(routes) if isinstance(routes, dict) else len(routes or [])
    blockers = []
    if isinstance(contract, dict):
        for key in ("reason", "blocker", "latest_blocker"):
            if contract.get(key):
                blockers.append(str(contract.get(key)))
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": "OK" if route_count else "NO_DATA",
        "route_count": route_count,
        "source_proof_count": int(contract.get("source_proof_count", 0) or 0) if isinstance(contract, dict) else 0,
        "blockers": blockers,
        "fresh": True,
    }


def write_scanner_health(contract: Dict[str, Any] | None = None) -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data = build_scanner_health(contract)
    STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data
