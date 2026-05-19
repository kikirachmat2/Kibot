#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    p = Path("state/target_board_runtime.json")
    if not p.exists():
        print("target_board_runtime_missing")
        return 1
    payload = json.loads(p.read_text(encoding="utf-8"))
    if payload.get("indodax_count", 0) <= 0 and payload.get("phantom_count", 0) <= 0:
        print("target_board_empty")
        return 1
    print("ASSERT_TARGET_BOARD_RUNTIME_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
