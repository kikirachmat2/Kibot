#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

URL = "http://127.0.0.1:8787/api/control-plane"
REQUIRED_TOP_LEVEL = {
    "runtime",
    "portfolio_v6",
    "decision",
    "venues",
    "workflow",
    "opportunity_funnel",
    "ai_system",
    "orders",
    "logs",
    "debug",
}


def main() -> int:
    try:
        payload = httpx.get(URL, timeout=6.0).json()
    except Exception as exc:
        print(f"FAIL:fetch_error:{exc}")
        return 1
    missing = sorted(key for key in REQUIRED_TOP_LEVEL if key not in payload)
    if missing:
        print(f"FAIL:missing_keys={missing}")
        return 1
    runtime = payload.get("runtime") or {}
    portfolio = payload.get("portfolio_v6") or {}
    decision = payload.get("decision") or {}
    if runtime.get("mode") != "LIVE_ONLY":
        print(f"FAIL:runtime_mode={runtime.get('mode')}")
        return 1
    if portfolio.get("total_equity_idr") is None:
        print("FAIL:portfolio_missing_total_equity")
        return 1
    if "current_action" not in decision:
        print("FAIL:decision_missing_current_action")
        return 1
    print("OK:DASHBOARD_V6_PAYLOAD")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
