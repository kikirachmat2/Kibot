#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / "state"


def _read_json(name: str) -> dict[str, Any]:
    try:
        data = json.loads((STATE / name).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _age_s(name: str) -> float:
    try:
        return time.time() - (STATE / name).stat().st_mtime
    except Exception:
        return -1.0


def main() -> int:
    blockers: list[str] = []
    state = _read_json("workflow_automation.json")
    if not state:
        blockers.append("workflow_automation_missing")
    else:
        age = _age_s("workflow_automation.json")
        if age < 0 or age > 90:
            blockers.append(f"workflow_automation_stale:{int(age)}s")
        if not state.get("overall_status"):
            blockers.append("overall_status_missing")
        if not state.get("current_best_action"):
            blockers.append("current_best_action_missing")
        steps = state.get("workflow_steps")
        if not isinstance(steps, list) or len(steps) < 5:
            blockers.append("workflow_steps_incomplete")
        money = state.get("money_truth")
        if not isinstance(money, dict) or "total_balance_idr" not in money:
            blockers.append("money_truth_missing")
        telegram = state.get("telegram")
        if not isinstance(telegram, dict) or "configured" not in telegram:
            blockers.append("telegram_status_missing")
        support_tools = state.get("support_tools")
        if not isinstance(support_tools, dict) or not support_tools.get("gh"):
            blockers.append("support_tools_missing_gh")

    if blockers:
        print("ASSERT_WORKFLOW_AUTOMATION_BLOCKED", "; ".join(blockers))
        return 1
    print("ASSERT_WORKFLOW_AUTOMATION_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
