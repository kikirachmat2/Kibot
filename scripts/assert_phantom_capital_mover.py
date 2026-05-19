#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"


def main() -> int:
    p = STATE / "phantom_capital_mover.json"
    if not p.exists():
        print("ASSERT_PHANTOM_CAPITAL_MOVER_FAILED")
        print("phantom_capital_mover_missing")
        return 1
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("bridge") != "OFF" or data.get("withdrawal") != "OFF":
        print("ASSERT_PHANTOM_CAPITAL_MOVER_FAILED")
        print("bridge_or_withdrawal_on")
        return 1
    if not data.get("recommended_action"):
        print("ASSERT_PHANTOM_CAPITAL_MOVER_FAILED")
        print("missing_recommended_action")
        return 1
    print("ASSERT_PHANTOM_CAPITAL_MOVER_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

