#!/usr/bin/env python3
"""Fail if production dashboard responses contain legacy mode labels."""

from __future__ import annotations

import json
import sys
import urllib.request

ENDPOINTS = [
    "http://127.0.0.1:8787/",
    "http://127.0.0.1:8787/api/control-plane",
]
FORBIDDEN = ("paper", "sim", "mock", "canary", "view-only")


def main() -> int:
    for url in ENDPOINTS:
        with urllib.request.urlopen(url, timeout=5) as res:
            body = res.read().decode("utf-8", errors="ignore").lower()
        hits = [term for term in FORBIDDEN if term in body]
        if hits:
            print(json.dumps({"url": url, "hits": hits}, indent=2))
            return 1
    print("OK: no legacy modes found in dashboard/control-plane.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
