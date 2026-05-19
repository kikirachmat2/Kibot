from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
BASE_EXECUTOR_STATE_FILE = STATE_DIR / "base_executor_state.json"


def write_base_state(payload: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    BASE_EXECUTOR_STATE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
