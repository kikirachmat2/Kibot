#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from pathlib import Path

STATE = Path("state")
REQUIRED = [
    "engine_independence.json",
    "capital_governor.json",
    "indodax_scanner_state.json",
    "indodax_no_idle.json",
    "indodax_top_targets.json",
    "phantom_treasury.json",
    "phantom_capital_mover.json",
    "phantom_network_maximizer.json",
    "phantom_top_targets.json",
    "deadline_profit_enforcer.json",
    "scanner_executor_contract.json",
    "scanner_health.json",
    "server_telemetry.json",
    "ai_strategy_review.json",
]


def main() -> int:
    missing = [name for name in REQUIRED if not (STATE / name).exists()]
    if missing:
        print(f"missing_state_files:{','.join(missing)}")
        return 1
    stale = []
    bad = []
    for name in REQUIRED:
        try:
            path = STATE / name
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            bad.append(name)
            continue
        if not isinstance(payload, dict):
            bad.append(name)
            continue
        age = time.time() - path.stat().st_mtime
        if age > 900:
            stale.append(name)
    if bad:
        print(f"invalid_state_files:{','.join(bad)}")
        return 1
    if stale:
        print(f"stale_state_files:{','.join(stale)}")
        return 1
    print("ASSERT_SERVER_TRUTH_RUNTIME_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
