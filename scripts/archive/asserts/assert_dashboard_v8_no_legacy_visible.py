#!/usr/bin/env python3
from __future__ import annotations

import httpx

ROOT_URL = "http://127.0.0.1:8787/"
CONTROL_URL = "http://127.0.0.1:8787/api/control-plane"
FORBIDDEN = (
    "CONTROLLED-LIVE",
    "Controlled Live",
    "Project Info",
    "Blocked Reason",
    "Indodax Shadow",
    "VIEW ONLY",
    "Live trading OFF",
)


def main() -> int:
    try:
        html = httpx.get(ROOT_URL, timeout=6.0).text
        payload = httpx.get(CONTROL_URL, timeout=6.0).json()
    except Exception as exc:
        print(f"FAIL:fetch_error:{exc}")
        return 1

    payload_text = str(payload)
    for word in FORBIDDEN:
        if word.lower() in html.lower():
            print(f"FAIL:legacy_visible_html:{word}")
            return 1
        if word.lower() in payload_text.lower():
            print(f"FAIL:legacy_visible_payload:{word}")
            return 1

    print("OK:DASHBOARD_V8_NO_LEGACY_VISIBLE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
