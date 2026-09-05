#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    state = root / "state" / "live_truth.json"
    if not state.exists():
        print("FAIL:live_truth_missing")
        return 1
    data = json.loads(state.read_text(encoding="utf-8"))
    if data.get("runtime_mode") != "LIVE_ONLY":
        print(f"FAIL:runtime_mode={data.get('runtime_mode')}")
        return 1
    forbidden = ("paper", "mock", "canary", "shadow")
    for key, value in data.items():
        if any(w in str(key).lower() for w in forbidden):
            print(f"FAIL:forbidden_key:{key}")
            return 1
        if isinstance(value, str) and any(w in value.lower() for w in forbidden):
            print(f"FAIL:forbidden_value:{key}")
            return 1
    print("OK:DASHBOARD_LIVE_TRUTH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

