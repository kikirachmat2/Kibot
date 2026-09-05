#!/usr/bin/env python3
from __future__ import annotations

import httpx

URL = "http://127.0.0.1:8787/"


def main() -> int:
    try:
        html = httpx.get(URL, timeout=6.0).text
    except Exception as exc:
        print(f"FAIL:fetch_error:{exc}")
        return 1

    required = (
        "KiBot Live Command Center",
        "section-nav",
        "Overview",
        "Workflow",
        "Venues",
        "AI System",
        "Orders",
        "Logs",
        "Debug",
        "status-banner",
        "page-container",
    )
    missing = [word for word in required if word.lower() not in html.lower()]
    if missing:
        print(f"FAIL:missing_layout={missing}")
        return 1
    print("OK:DASHBOARD_V8_OPERATOR_LAYOUT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
