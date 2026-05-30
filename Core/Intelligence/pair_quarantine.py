from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = ROOT / "state"
PAIR_FILE = STATE_DIR / "pair_quarantine.json"
WIB = timezone(timedelta(hours=7))


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def load_pair_quarantine() -> Dict[str, Any]:
    return _read_json(PAIR_FILE, {"blocked_pairs": [], "updated_at": ""})


def is_quarantined(pair: str) -> bool:
    data = load_pair_quarantine()
    blocked = data.get("blocked_pairs", [])
    if not isinstance(blocked, list):
        return False
    return str(pair or "").upper() in {str(x).upper() for x in blocked}


def quarantine_pair(pair: str, reason: str, seconds: int = 86400) -> Dict[str, Any]:
    data = load_pair_quarantine()
    if not isinstance(data, dict):
        data = {"blocked_pairs": []}
    blocked = data.get("blocked_pairs", [])
    if not isinstance(blocked, list):
        blocked = []
    pair_u = str(pair or "").upper()
    blocked = [x for x in blocked if str(x).upper() != pair_u]
    blocked.append(pair_u)
    record = {
        "pair": pair_u,
        "reason": reason,
        "until": (datetime.now(WIB) + timedelta(seconds=int(seconds))).isoformat(),
    }
    data["blocked_pairs"] = blocked
    data["last_record"] = record
    data["updated_at"] = datetime.now(WIB).isoformat()
    PAIR_FILE.parent.mkdir(parents=True, exist_ok=True)
    PAIR_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return data

