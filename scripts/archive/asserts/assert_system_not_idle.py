#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / "state"


def main() -> int:
    p = STATE / "autonomous_trading_brain.json"
    if not p.exists():
        print("ASSERT_SYSTEM_NOT_IDLE_FAILED")
        print("autonomous_trading_brain_missing")
        return 1
    data = json.loads(p.read_text(encoding="utf-8"))
    if str(data.get("next_action") or "").upper() in {"", "WAIT"}:
        print("ASSERT_SYSTEM_NOT_IDLE_FAILED")
        print("generic_wait")
        return 1
    print("ASSERT_SYSTEM_NOT_IDLE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
