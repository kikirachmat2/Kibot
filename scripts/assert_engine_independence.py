#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"


def main() -> int:
    p = STATE / "engine_independence.json"
    if not p.exists():
        print("ASSERT_ENGINE_INDEPENDENCE_FAILED")
        print("engine_independence_missing")
        return 1
    data = json.loads(p.read_text(encoding="utf-8"))
    indodax_only = os.getenv("KIBOT_INDODAX_ONLY", "true").lower() in {"1", "true", "yes", "on"}
    if indodax_only:
        if data.get("bridge") != "OFF" or data.get("withdrawal") != "OFF":
            print("ASSERT_ENGINE_INDEPENDENCE_FAILED")
            print("bridge_or_withdrawal_not_retired")
            return 1
    elif data.get("bridge") != "ON" or data.get("withdrawal") != "ON":
        print("ASSERT_ENGINE_INDEPENDENCE_FAILED")
        print("bridge_or_withdrawal_not_active")
        return 1
    indo = data.get("indodax_engine", {})
    ph = data.get("phantom_engine", {})
    if indo.get("status") == "BLOCKED_WITH_REASON" and not indodax_only and ph.get("status") == "BLOCKED_WITH_REASON":
        print("ASSERT_ENGINE_INDEPENDENCE_FAILED")
        print("both_engines_blocked")
        return 1
    print("ASSERT_ENGINE_INDEPENDENCE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
