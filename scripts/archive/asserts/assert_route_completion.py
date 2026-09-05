#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.request
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
CONTROL = STATE / "control_plane.json"

def fail(msg: str, code: int = 1) -> None:
    print(f"ASSERT_ROUTE_COMPLETION_FAILED: {msg}", file=sys.stderr)
    raise SystemExit(code)


def main() -> None:
    try:
        raw = urllib.request.urlopen("http://127.0.0.1:8787/api/control-plane", timeout=8).read().decode()
        payload = json.loads(raw)
    except Exception:
        if not CONTROL.exists():
            fail("control plane unavailable and state/control_plane.json missing")
        try:
            payload = json.loads(CONTROL.read_text())
        except Exception as exc:
            fail(f"invalid control plane json: {exc}")
    routes = payload.get("scanner_executor_contract", {}).get("routes", []) if isinstance(payload, dict) else []
    if not isinstance(routes, list) or not any(isinstance(route, dict) and route.get("route") == "indodax" for route in routes):
        fail("indodax route missing from scanner executor contract")
    if any(isinstance(route, dict) and route.get("route") != "indodax" for route in routes):
        fail("non-indodax route present")
    print("ASSERT_ROUTE_COMPLETION_OK")


if __name__ == "__main__":
    main()
