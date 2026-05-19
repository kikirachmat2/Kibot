#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"


def main() -> int:
    p = STATE / "deadline_profit_enforcer.json"
    if not p.exists():
        print("ASSERT_DEADLINE_PRESSURE_FAILED")
        print("deadline_state_missing")
        return 1
    data = json.loads(p.read_text(encoding="utf-8"))
    if not data.get("stage") and not data.get("pressure_level"):
        print("ASSERT_DEADLINE_PRESSURE_FAILED")
        print("missing_stage")
        return 1
    print("ASSERT_DEADLINE_PRESSURE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

