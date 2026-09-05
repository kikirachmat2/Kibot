#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    p = Path("state/indodax_top_targets.json")
    if not p.exists():
        print("indodax_top_targets_missing")
        return 1
    payload = json.loads(p.read_text(encoding="utf-8"))
    if not payload.get("top_targets"):
        print(f"indodax_top_targets_empty:{payload.get('why_empty', '')}")
        return 1
    print("ASSERT_INDODAX_TOP_TARGETS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
