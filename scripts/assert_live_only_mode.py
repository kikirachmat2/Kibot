#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

from Core.Support.runtime_mode_guard import normalize_runtime_mode, LIVE_ONLY


def main() -> int:
    mode = normalize_runtime_mode(os.getenv("KIBOT_RUNTIME_MODE", os.getenv("KIBOT_TRADING_MODE", "")))
    if mode != LIVE_ONLY:
        print(f"BLOCKED:{mode}")
        return 1
    print("OK:LIVE_ONLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

