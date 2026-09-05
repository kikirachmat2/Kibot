#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / "state"


def main() -> int:
    p = STATE / "autonomous_trading_brain.json"
    if not p.exists():
        print("ASSERT_GUARD_NOT_OVERBLOCKING_FAILED")
        print("brain_missing")
        return 1
    data = json.loads(p.read_text(encoding="utf-8"))
    fatal = data.get("fatal_blockers", [])
    advisory = data.get("advisory_signals", [])
    if fatal and str(data.get("current_best_action") or "").upper() == "WAIT":
        print("ASSERT_GUARD_NOT_OVERBLOCKING_FAILED")
        print("fatal_blockers_forced_wait")
        return 1
    if str(data.get("next_action") or "").upper() in {"", "WAIT"}:
        print("ASSERT_GUARD_NOT_OVERBLOCKING_FAILED")
        print("no_next_action")
        return 1
    print("ASSERT_GUARD_NOT_OVERBLOCKING_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
