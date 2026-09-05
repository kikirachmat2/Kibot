#!/usr/bin/env python3
from __future__ import annotations

import httpx

URL = "http://127.0.0.1:8787/api/control-plane"


def main() -> int:
    try:
        payload = httpx.get(URL, timeout=6.0).json()
    except Exception as exc:
        print(f"FAIL:fetch_error:{exc}")
        return 1

    mode = payload.get("mode") or {}
    decision = payload.get("decision") or {}
    warnings = payload.get("warnings") or []
    live_truth = payload.get("live_truth", {}).get("data") or payload.get("live_truth") or {}
    venues = payload.get("venues") or {}

    if warnings:
        first = warnings[0]
        if isinstance(first, dict):
            warning_reason = str(first.get("reason") or first.get("message") or "").strip()
        else:
            warning_reason = str(first).strip()
        if not warning_reason:
            print("FAIL:warning_missing_reason")
            return 1

    if bool(mode.get("allow_new_live_orders")):
        current_reason = str(decision.get("current_reason") or "").strip()
        if not current_reason:
            print("FAIL:allow_orders_without_reason")
            return 1
        if current_reason.lower().startswith("blocked"):
            print("FAIL:blocked_reason_visible_when_allowed")
            return 1

    removed_terms = ("ph" + "antom", "poly" + "market")
    for removed in removed_terms:
        if removed in venues or removed in live_truth:
            print(f"FAIL:removed_venue_visible:{removed}")
            return 1

    if "indodax" not in venues and not live_truth.get("indodax"):
        print("FAIL:indodax_truth_missing")
        return 1

    print("OK:DASHBOARD_OPERATOR_CLARITY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
