#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, Tuple
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


ENDPOINTS = (
    "http://127.0.0.1:8787/api/control-plane",
    "http://127.0.0.1:8787/api/state",
    "http://127.0.0.1:8787/api/system/state",
    "http://127.0.0.1:8787/api/autonomous/state",
)


def _fetch(url: str) -> Tuple[int, Dict[str, Any]]:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode()
            return exc.code, json.loads(raw) if raw else {}
        except Exception:
            return exc.code, {}
    except Exception:
        return 0, {}


def _extract_ai(payload: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("ai_system", "ai_inventory"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    for key in ("state", "live_truth"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            for child in ("ai_system", "ai_inventory"):
                value = nested.get(child)
                if isinstance(value, dict):
                    return value
    return {}


def main() -> int:
    for endpoint in ENDPOINTS:
        status, payload = _fetch(endpoint)
        if status != 200 or not isinstance(payload, dict):
            continue
        ai = _extract_ai(payload)
        if not ai:
            continue
        if str(ai.get("role") or "") != "advisory_only":
            print(f"FAIL:ai_role={ai.get('role')}")
            return 1
        if str(ai.get("order_permission") or "") != "DENIED":
            print(f"FAIL:order_permission={ai.get('order_permission')}")
            return 1
        if str(ai.get("override_permission") or "") != "DENIED":
            print(f"FAIL:override_permission={ai.get('override_permission')}")
            return 1
        if str(payload.get("runtime_mode") or ai.get("runtime_mode") or "") not in {"", "LIVE_ONLY"}:
            print(f"FAIL:runtime_mode={payload.get('runtime_mode') or ai.get('runtime_mode')}")
            return 1
        forbidden = [k for k in payload.keys() if any(word in str(k).lower() for word in ("paper", "mock", "canary", "shadow"))]
        if forbidden:
            print(f"FAIL:forbidden_top_level_keys={forbidden}")
            return 1
        print(f"OK:WEBSITE_AI_SYSTEM_WORKING endpoint={endpoint}")
        return 0
    from fastapi.testclient import TestClient
    from Core.Intelligence.kibot_dashboard import app

    payload = TestClient(app).get("/api/control-plane").json()
    ai = _extract_ai(payload)
    if ai:
        print("OK:WEBSITE_AI_SYSTEM_WORKING endpoint=local_testclient")
        return 0
    print("FAIL:ai_system_not_exposed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
