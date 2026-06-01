#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    path = Path("state/recovery_reset_plan.json")
    if not path.exists():
        raise SystemExit("FAIL:RECOVERY_RESET_PLAN_MISSING")
    data = json.loads(path.read_text())
    if str(data.get("current_state") or "") != "LOCKED_DAILY_LOSS":
        raise SystemExit("FAIL:RECOVERY_RESET_PLAN_INVALID_STATE")
    if int(data.get("max_round_trips", 0) or 0) != 3:
        raise SystemExit("FAIL:RECOVERY_RESET_PLAN_MAX_ROUND_TRIPS")
    if int(data.get("max_micro_probes", 0) or 0) != 1:
        raise SystemExit("FAIL:RECOVERY_RESET_PLAN_MAX_MICRO_PROBES")
    if bool(data.get("scale_up", True)) is not False:
        raise SystemExit("FAIL:RECOVERY_RESET_PLAN_SCALE_UP")
    print("OK:RECOVERY_RESET_PLAN")


if __name__ == "__main__":
    main()
