#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import urllib.request


def main() -> int:
    p = Path("state/server_telemetry.json")
    if not p.exists():
        print("server_telemetry_missing")
        return 1
    payload = json.loads(p.read_text(encoding="utf-8"))
    for key in ("cpu", "ram", "disk"):
        if key not in payload:
            print(f"missing_telemetry_field:{key}")
            return 1
    print("ASSERT_TELEMETRY_RUNTIME_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
