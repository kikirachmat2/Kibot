#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from Core.Support.recovery_reset_plan import build_recovery_reset_plan
from Core.Support.money_movement_audit import load_state_bundle


def main() -> None:
    path = Path("state/recovery_reset_plan.json")
    data = build_recovery_reset_plan(load_state_bundle())
    if path.exists():
        try:
            file_data = json.loads(path.read_text())
            if isinstance(file_data, dict) and file_data.get("next_reset_at"):
                data = file_data
        except Exception:
            pass
    if str(data.get("current_state") or "") not in {"LOCKED_DAILY_LOSS", "CONSERVATIVE_RECOVERY"}:
        raise SystemExit("FAIL:RECOVERY_RESET_PLAN_INVALID_STATE")
    next_reset_at = str(data.get("next_reset_at") or "")
    if not next_reset_at:
        raise SystemExit("FAIL:RECOVERY_RESET_PLAN_NEXT_RESET_EMPTY")
    if int(data.get("max_round_trips", 0) or 0) != 3:
        raise SystemExit("FAIL:RECOVERY_RESET_PLAN_MAX_ROUND_TRIPS")
    if int(data.get("max_micro_probes", 0) or 0) != 1:
        raise SystemExit("FAIL:RECOVERY_RESET_PLAN_MAX_MICRO_PROBES")
    if bool(data.get("scale_up", True)) is not False:
        raise SystemExit("FAIL:RECOVERY_RESET_PLAN_SCALE_UP")
    if str(data.get("timezone") or "") != "Asia/Jakarta":
        raise SystemExit("FAIL:RECOVERY_RESET_PLAN_TIMEZONE")
    print("OK:RECOVERY_RESET_PLAN")


if __name__ == "__main__":
    main()
