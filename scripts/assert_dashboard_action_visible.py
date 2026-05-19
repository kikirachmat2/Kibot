#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"


def main() -> int:
    for name in ["autonomous_trading_brain.json", "indodax_live_brain.json", "phantom_live_brain.json"]:
        p = STATE / name
        if not p.exists():
            print("ASSERT_DASHBOARD_ACTION_VISIBLE_FAILED")
            print(f"missing:{name}")
            return 1
        data = json.loads(p.read_text(encoding="utf-8"))
        if not str(data.get("next_action") or "").strip():
            print("ASSERT_DASHBOARD_ACTION_VISIBLE_FAILED")
            print(f"missing_next_action:{name}")
            return 1
    print("ASSERT_DASHBOARD_ACTION_VISIBLE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
