#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "live_truth.json"


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def main() -> int:
    if not STATE.exists():
        print("FAIL:state/live_truth.json missing")
        return 1
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"FAIL:json_error:{exc}")
        return 1
    if data.get("runtime_mode") != "LIVE_ONLY":
        print(f"FAIL:runtime_mode={data.get('runtime_mode')}")
        return 1
    updated_at = str(data.get("updated_at") or "")
    if not updated_at:
        print("FAIL:updated_at missing")
        return 1
    age = (datetime.now(timezone.utc) - _parse_dt(updated_at).astimezone(timezone.utc)).total_seconds()
    if age > 90:
        print(f"FAIL:live_truth stale age={age:.1f}s")
        return 1
    required = [
        "risk_state",
        "total_equity_idr",
        "wallet_equity_idr",
        "cash_idr",
        "realized_pnl_today_idr",
        "unrealized_pnl_idr",
        "fees_today_idr",
        "net_pnl_today_idr",
        "open_positions",
        "dust_positions",
        "blocked_pairs",
        "indodax",
    ]
    missing = [k for k in required if k not in data]
    if missing:
        print(f"FAIL:missing_keys={missing}")
        return 1
    top_forbidden = {"paper", "mock", "canary", "shadow"}
    bad = sorted(k for k in data.keys() if str(k).lower() in top_forbidden)
    if bad:
        print(f"FAIL:forbidden_keys={bad}")
        return 1
    print(f"OK:LIVE_TRUTH_FRESH age={age:.1f}s risk={data.get('risk_state')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
