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
    routes = payload.get("web3", {}).get("routes", {}) if isinstance(payload, dict) else {}
    base = routes.get("base", {}) if isinstance(routes, dict) else {}
    future = routes.get("future_web3", {}) if isinstance(routes, dict) else {}
    if base.get("executor") is False and "reason" not in base:
        fail("base executor false without reason")
    if future.get("executor") is False and "reason" not in future:
        fail("future web3 executor false without reason")
    print("ASSERT_ROUTE_COMPLETION_OK")


if __name__ == "__main__":
    main()
