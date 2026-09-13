#!/usr/bin/env python3
from __future__ import annotations

import httpx

URL = "http://127.0.0.1:8787/api/control-plane"
REQUIRED = {
    "runtime",
    "portfolio_v8",
    "decision",
    "venues_v8",
    "workflow_v8",
    "opportunity_funnel",
    "ai_system",
    "orders_v8",
    "logs_v8",
    "debug",
}


def main() -> int:
    try:
      payload = httpx.get(URL, timeout=6.0).json()
    except Exception as exc:
      print(f"FAIL:fetch_error:{exc}")
      return 1

    missing = sorted(key for key in REQUIRED if key not in payload)
    if missing:
      print(f"FAIL:missing_keys={missing}")
      return 1
    runtime = payload.get("runtime") or {}
    if str(runtime.get("mode") or "").upper() != "LIVE_ONLY":
      print(f"FAIL:runtime_mode={runtime.get('mode')}")
      return 1
    print("OK:DASHBOARD_V8_PAYLOAD")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
