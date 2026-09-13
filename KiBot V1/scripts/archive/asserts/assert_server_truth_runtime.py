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
    "deadline_profit_enforcer.json",
    "scanner_executor_contract.json",
    "scanner_health.json",
    "server_telemetry.json",
]

AI_REVIEW_ALTERNATIVES = [
    "ai_strategy_review.json",
    "agent_self_critique.json",
    "ai_system_inventory.json",
]


def main() -> int:
    missing = [name for name in REQUIRED if not (STATE / name).exists()]
    if not any((STATE / name).exists() for name in AI_REVIEW_ALTERNATIVES):
        missing.append("ai_review_state")
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
    review_candidates = [name for name in AI_REVIEW_ALTERNATIVES if (STATE / name).exists()]
    review_fresh = False
    for name in review_candidates:
        try:
            payload = json.loads((STATE / name).read_text(encoding="utf-8"))
        except Exception:
            bad.append(name)
            continue
        if not isinstance(payload, dict):
            bad.append(name)
            continue
        age = time.time() - (STATE / name).stat().st_mtime
        if age <= 900:
            review_fresh = True
    if review_candidates and not review_fresh:
        stale.append("ai_review_state")
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
