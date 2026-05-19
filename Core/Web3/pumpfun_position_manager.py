from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
POSITIONS_FILE = STATE_DIR / "pumpfun_positions.json"
EXIT_STATE_FILE = STATE_DIR / "pumpfun_exit_state.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_json(path: Path, payload: Any) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


class PumpfunPositionManager:
    def load_positions(self) -> List[Dict[str, Any]]:
        payload = _read_json(POSITIONS_FILE, [])
        return payload if isinstance(payload, list) else []

    def save_positions(self, positions: List[Dict[str, Any]]) -> None:
        _write_json(POSITIONS_FILE, positions)

    def load_exit_state(self) -> Dict[str, Any]:
        return _read_json(EXIT_STATE_FILE, {})

    def save_exit_state(self, payload: Dict[str, Any]) -> None:
        _write_json(EXIT_STATE_FILE, payload)

    def mark_exit(self, position_id: str, reason: str, status: str) -> None:
        positions = self.load_positions()
        updated = []
        for pos in positions:
            if str(pos.get("id") or "") == str(position_id):
                pos["status"] = status
                pos["exit_reason"] = reason
                pos["updated_at"] = datetime.now(timezone.utc).isoformat()
            updated.append(pos)
        self.save_positions(updated)

