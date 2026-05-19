from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
BASE_POSITIONS_FILE = STATE_DIR / "base_positions.json"
BASE_EXIT_STATE_FILE = STATE_DIR / "base_exit_state.json"


def _read(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default


class BasePositionManager:
    def list_positions(self) -> List[Dict[str, Any]]:
        payload = _read(BASE_POSITIONS_FILE, [])
        return payload if isinstance(payload, list) else []

    def record_position(self, position: Dict[str, Any]) -> None:
        payload = self.list_positions()
        payload.append(position)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        BASE_POSITIONS_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    def update_exit_state(self, payload: Dict[str, Any]) -> None:
        payload = {"updated_at": datetime.now(timezone.utc).isoformat(), **payload}
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        BASE_EXIT_STATE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
