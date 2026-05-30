#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "live_truth.json"


def main() -> int:
    if not STATE.exists():
        print("FAIL:live_truth_missing")
        return 1
    try:
        live_truth = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        print("FAIL:live_truth_invalid")
        return 1
    phantom = live_truth.get("phantom", {}) if isinstance(live_truth, dict) else {}
    status = str(phantom.get("status") or "UNKNOWN")
    if status == "OK":
        print("OK:PHANTOM_RUNTIME_AUTONOMY")
        return 0
    if status == "LOCKED_MISSING_ENV":
        print("OK:PHANTOM_LOCKED_MISSING_ENV")
        return 0
    if status in {"BLOCKED_BY_PHANTOM_SIGNING", "BLOCKED_BY_RPC", "BLOCKED_BY_JUPITER", "BLOCKED_BY_WALLET_RECONCILIATION", "BLOCKED_WITH_REASON"}:
        print(f"BLOCKED:{status}")
        return 0
    if status.startswith("OK:PHANTOM"):
        print(status)
        return 0
    print(f"BLOCKED:{status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
