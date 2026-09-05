#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / "state"


def read_json(path: Path):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def stale(path: Path, max_age_s: int = 180) -> bool:
    if not path.exists():
        return True
    return (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) > max_age_s


def resolve_state_path(raw: str) -> Path:
    if not raw:
        return STATE / ""
    path = Path(raw)
    if path.is_absolute():
        return path
    if raw.startswith("state/") or raw.startswith("state\\"):
        return ROOT / raw
    return STATE / raw


def main() -> int:
    contract = read_json(STATE / "scanner_executor_contract.json") or {}
    routes = contract.get("routes", []) if isinstance(contract, dict) else []
    problems = []
    for route in routes:
        if not isinstance(route, dict):
            continue
        name = route.get("route", "unknown")
        scanner_file = resolve_state_path(str(route.get("scanner_state_file") or ""))
        executor_file = resolve_state_path(str(route.get("executor_state_file") or ""))
        if not route.get("scanner_state_file") or not route.get("executor_state_file"):
            problems.append((name, "route_hidden_from_contract"))
        if stale(scanner_file):
            problems.append((name, "scanner_missing_or_stale"))
        if not executor_file.exists():
            problems.append((name, "executor_state_missing"))
        if route.get("status") == "LIVE_READY" and route.get("reason") in {"", "runtime_verified"}:
            pass
        elif route.get("status") == "LIVE_READY":
            problems.append((name, f"unexpected_ready_reason:{route.get('reason')}"))

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "checked_routes": len(routes),
        "problems": problems,
        "status": "PASS" if not problems else "FAIL",
    }
    (STATE / "scanner_executor_contract_runtime.json").write_text(json.dumps(payload, indent=2))
    if problems:
        print("ASSERT_SCANNER_EXECUTOR_COVERAGE_FAILED")
        for route, reason in problems[:200]:
            print(f"{route}: {reason}")
        return 1
    print("ASSERT_SCANNER_EXECUTOR_COVERAGE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
