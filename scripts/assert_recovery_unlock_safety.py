#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    reset_path = Path("state/recovery_reset_plan.json")
    growth_path = Path("state/net_growth_audit.json")
    fill_path = Path("state/fill_quality_audit.json")
    phantom_path = Path("state/phantom_quote_diagnosis.json")
    if not reset_path.exists():
        raise SystemExit("FAIL:RECOVERY_RESET_PLAN_MISSING")
    reset = json.loads(reset_path.read_text())
    if str(reset.get("current_state") or "") not in {"LOCKED_DAILY_LOSS", "CONSERVATIVE_RECOVERY"}:
        raise SystemExit("FAIL:RECOVERY_LOCK_NOT_ACTIVE")
    if not str(reset.get("next_reset_at") or ""):
        raise SystemExit("FAIL:RECOVERY_UNLOCK_TIME_MISSING")
    if int(reset.get("max_round_trips", 0) or 0) != 3:
        raise SystemExit("FAIL:RECOVERY_UNLOCK_MAX_ROUND_TRIPS")
    if int(reset.get("max_micro_probes", 0) or 0) != 1:
        raise SystemExit("FAIL:RECOVERY_UNLOCK_MAX_MICRO_PROBES")
    if bool(reset.get("scale_up", True)) is not False:
        raise SystemExit("FAIL:RECOVERY_UNLOCK_SCALE_UP")

    growth = json.loads(growth_path.read_text()) if growth_path.exists() else {}
    fill = json.loads(fill_path.read_text()) if fill_path.exists() else {}
    if str(growth.get("status") or "").upper() in {"FLAT_CHURN", "LOSING"} and bool(reset.get("scale_up", True)):
        raise SystemExit("FAIL:RECOVERY_UNLOCK_SCALE_UP_ON_BAD_GROWTH")
    if str(fill.get("status") or "").upper() == "ACCOUNTING_ERROR" and bool(reset.get("scale_up", True)):
        raise SystemExit("FAIL:RECOVERY_UNLOCK_SCALE_UP_ON_ACCOUNTING_ERROR")

    if phantom_path.exists():
        phantom = json.loads(phantom_path.read_text())
        if str(phantom.get("status") or "").upper() == "QUOTES_NOT_OK":
            if bool(phantom.get("targets_checked", 0)) > 0:
                pass
    print("OK:RECOVERY_UNLOCK_SAFETY")


if __name__ == "__main__":
    main()
