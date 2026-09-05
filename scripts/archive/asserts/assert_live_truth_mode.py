#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
import urllib.request


FORBIDDEN = re.compile(r"\bpaper\b|\bsim\b|\bmock\b|\bcanary\b|view-only", re.IGNORECASE)
URLS = ("http://127.0.0.1:8787/", "http://127.0.0.1:8787/api/control-plane")


def main() -> int:
    for url in URLS:
        with urllib.request.urlopen(url, timeout=5) as res:
            body = res.read().decode("utf-8", errors="replace")
        if FORBIDDEN.search(body):
            print(f"FORBIDDEN_LEGACY_WORDS_FOUND {url}")
            return 1
    print("LIVE_TRUTH_MODE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

