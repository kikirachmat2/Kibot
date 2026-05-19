#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"


def main() -> int:
    checks = ["capital_governor.json", "engine_independence.json", "phantom_capital_mover.json"]
    for name in checks:
        p = STATE / name
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        if str(data.get("bridge", "OFF")).upper() != "OFF" or str(data.get("withdrawal", "OFF")).upper() != "OFF":
            print("ASSERT_NO_BRIDGE_WITHDRAWAL_RUNTIME_FAILED")
            print(f"{name}: bridge/withdrawal on")
            return 1
    print("ASSERT_NO_BRIDGE_WITHDRAWAL_RUNTIME_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

