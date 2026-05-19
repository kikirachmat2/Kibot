#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"


def main() -> int:
    gov = json.loads((STATE / "capital_governor.json").read_text(encoding="utf-8")) if (STATE / "capital_governor.json").exists() else {}
    eng = json.loads((STATE / "engine_independence.json").read_text(encoding="utf-8")) if (STATE / "engine_independence.json").exists() else {}
    indo = eng.get("indodax_engine", {})
    ph = eng.get("phantom_engine", {})
    if indo.get("allow_orders") is False and "phantom" in str(indo.get("reason", "")).lower():
        print("ASSERT_INDODAX_NOT_BLOCKED_BY_PHANTOM_FAILED")
        print("indodax_blocked_by_phantom")
        return 1
    if gov.get("venues", {}).get("indodax", {}).get("allow_orders") is False and ph.get("status") == "BLOCKED_WITH_REASON" and indo.get("status") == "ACTIVE":
        print("ASSERT_INDODAX_NOT_BLOCKED_BY_PHANTOM_FAILED")
        print("global_gov_conflation")
        return 1
    print("ASSERT_INDODAX_NOT_BLOCKED_BY_PHANTOM_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

