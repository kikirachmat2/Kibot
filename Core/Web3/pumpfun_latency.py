from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
LATENCY_FILE = STATE_DIR / "pumpfun_latency.json"


def write_latency(payload: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "last_scan_ms": int(payload.get("last_scan_ms", 0) or 0),
        "last_route_detect_ms": int(payload.get("last_route_detect_ms", 0) or 0),
        "last_sizing_ms": int(payload.get("last_sizing_ms", 0) or 0),
        "last_build_tx_ms": int(payload.get("last_build_tx_ms", 0) or 0),
        "last_submit_ms": int(payload.get("last_submit_ms", 0) or 0),
        "last_confirm_ms": int(payload.get("last_confirm_ms", 0) or 0),
        "hot_path_total_ms": int(payload.get("hot_path_total_ms", 0) or 0),
        "decision_source": str(payload.get("decision_source") or "script_only"),
    }
    LATENCY_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

