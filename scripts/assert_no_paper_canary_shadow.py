#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


FORBIDDEN = {"paper", "canary", "shadow", "mock"}


def _walk(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_walk(v) for v in value.values())
    if isinstance(value, list):
        return any(_walk(v) for v in value)
    if isinstance(value, str):
        return value.strip().lower() in FORBIDDEN
    return False


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    files = [
        root / "state" / "live_truth.json",
        root / "state" / "capital_governor.json",
        root / "state" / "daily_equity_anchor.json",
        root / "state" / "daily_equity_anchor_lock.json",
        root / "state" / "scanner_executor_contract.json",
        root / "state" / "indodax_top_targets.json",
    ]
    for file in files:
        if not file.exists():
            continue
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if _walk(data):
            print(f"BLOCKED:{file.name}")
            return 1
    print("OK:LEGACY_MODES_ABSENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
