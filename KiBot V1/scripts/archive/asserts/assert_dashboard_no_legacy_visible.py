#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from typing import Any

import httpx

ROOT_URL = "http://127.0.0.1:8787/"
CONTROL_URL = "http://127.0.0.1:8787/api/control-plane"
FORBIDDEN = (
    "CONTROLLED-LIVE",
    "Controlled Live",
    "Indodax Shadow",
    "VIEW ONLY",
    "Live trading OFF",
    "paper",
    "mock",
    "canary",
    "shadow",
    "soak",
    "simulation",
)


def _walk_visible(obj: Any, prefix: str = "") -> list[str]:
    lines: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if prefix == "" and key == "debug":
                continue
            lines.extend(_walk_visible(value, f"{prefix}.{key}" if prefix else key))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            lines.extend(_walk_visible(value, f"{prefix}[{idx}]"))
    elif isinstance(obj, str):
        lines.append(obj)
    return lines


def main() -> int:
    try:
        html = httpx.get(ROOT_URL, timeout=6.0).text
        payload = httpx.get(CONTROL_URL, timeout=6.0).json()
    except Exception as exc:
        print(f"FAIL:fetch_error:{exc}")
        return 1

    visible_payload = "\n".join(_walk_visible(payload))
    for word in FORBIDDEN:
        if word.lower() in html.lower():
            print(f"FAIL:legacy_visible_html:{word}")
            return 1
        if word.lower() in visible_payload.lower():
            print(f"FAIL:legacy_visible_payload:{word}")
            return 1

    print("OK:DASHBOARD_NO_LEGACY_VISIBLE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
