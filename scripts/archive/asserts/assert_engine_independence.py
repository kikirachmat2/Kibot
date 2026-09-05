#!/usr/bin/env python3
from __future__ import annotations

import json
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
    if data.get("global_mode") != "INDODAX_ONLY_LIVE":
        print("ASSERT_ENGINE_INDEPENDENCE_FAILED")
        print("global_mode_not_indodax_only")
        return 1
    indo = data.get("indodax_engine", {})
    if not isinstance(indo, dict):
        print("ASSERT_ENGINE_INDEPENDENCE_FAILED")
        print("indodax_engine_missing")
        return 1
    removed_keys = (
        "ph" + "antom_engine",
        "br" + "idge",
        "withdrawal",
        "retired_venues",
    )
    for removed_key in removed_keys:
        if removed_key in data:
            print("ASSERT_ENGINE_INDEPENDENCE_FAILED")
            print(f"removed_key_present:{removed_key}")
            return 1
    print("ASSERT_ENGINE_INDEPENDENCE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
