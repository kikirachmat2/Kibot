#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / "state" / "no_trade_forensics.json"


def main() -> int:
    if not STATE.exists():
        print("FAIL:no_trade_forensics_missing")
        return 1
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        print("FAIL:no_trade_forensics_invalid")
        return 1
    if not data.get("classification"):
        print("FAIL:classification_missing")
        return 1
    if not data.get("why_wait"):
        print("FAIL:why_wait_missing")
        return 1
    print(f"OK:NO_TRADE_FORENSICS classification={data.get('classification')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
