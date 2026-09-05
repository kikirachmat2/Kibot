#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / "state"


def main() -> int:
    p = STATE / "indodax_scanner_state.json"
    if not p.exists():
        print("ASSERT_INDODAX_MOMENTUM_SCANNER_FAILED")
        print("indodax_scanner_state_missing")
        return 1
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("scan_mode") != "REAL_EXCHANGE_MARKET_WIDE":
        print("ASSERT_INDODAX_MOMENTUM_SCANNER_FAILED")
        print("scan_mode_not_market_wide")
        return 1
    if not data.get("gainers_24h") or not data.get("volume_leaders"):
        print("ASSERT_INDODAX_MOMENTUM_SCANNER_FAILED")
        print("missing_gainers_or_volume_leaders")
        return 1
    print("ASSERT_INDODAX_MOMENTUM_SCANNER_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

