#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / "state"


def main() -> int:
    p = STATE / "indodax_live_brain.json"
    if not p.exists():
        print("ASSERT_INDODAX_BRAIN_ACTIVE_FAILED")
        print("brain_missing")
        return 1
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("engine") != "indodax":
        print("ASSERT_INDODAX_BRAIN_ACTIVE_FAILED")
        print("engine_mismatch")
        return 1
    print("ASSERT_INDODAX_BRAIN_ACTIVE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
