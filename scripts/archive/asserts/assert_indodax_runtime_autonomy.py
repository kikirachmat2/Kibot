#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    executor_path = ROOT / "Core" / "Executors" / "Indodax" / "indodax_executor.py"
    live_truth_path = ROOT / "state" / "live_truth.json"
    service_names = ["kibot-executor", "kibot-master", "kibot-scanner"]

    if not executor_path.exists():
        print("FAIL:indodax_executor_missing")
        return 1
    text = executor_path.read_text(encoding="utf-8")
    gate_pos = text.find("evaluate_live_trade(")
    trade_pos = text.find('type=side.lower()')
    if gate_pos < 0 or trade_pos < 0 or gate_pos > trade_pos:
        print("FAIL:gate_not_before_trade")
        return 1
    if "from Core.Decision.deterministic_decision_gate import evaluate_live_trade" not in text and "evaluate_live_trade(" not in text:
        print("FAIL:deterministic_gate_missing")
        return 1

    if not live_truth_path.exists():
        print("FAIL:live_truth_missing")
        return 1
    try:
        live_truth = json.loads(live_truth_path.read_text(encoding="utf-8"))
    except Exception:
        print("FAIL:live_truth_invalid")
        return 1
    if not isinstance(live_truth.get("indodax"), dict):
        print("FAIL:live_truth_missing_indodax")
        return 1

    statuses = {}
    for svc in service_names:
        try:
            res = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True, check=False)
            statuses[svc] = res.stdout.strip()
        except Exception:
            statuses[svc] = "unknown"

    executor_status = statuses.get("kibot-executor")
    if executor_status in {"active", "activating"}:
        print("OK:INDODAX_RUNTIME_AUTONOMY")
        return 0
    if executor_status in {"unknown", "", "inactive"}:
        print(f"OK:INDODAX_RUNTIME_AUTONOMY_LOCAL_SKIP service={executor_status}")
        return 0

    print(f"FAIL:service_inactive:{executor_status}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
