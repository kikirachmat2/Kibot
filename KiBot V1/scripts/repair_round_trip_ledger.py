#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from Core.Support.money_movement_audit import load_state_bundle
from Core.Support.round_trip_accounting import build_round_trip_accounting


def main() -> None:
    bundle = load_state_bundle()
    result = build_round_trip_accounting(bundle)
    stats = result.get("stats", {}) if isinstance(result, dict) else {}
    status = "OK:ROUND_TRIP_LEDGER_REPAIRED"
    if int(stats.get("accounting_errors", 0) or 0) > 0:
        status = "WARN:ROUND_TRIP_LEDGER_INCOMPLETE"
    if int(stats.get("closed_round_trips", 0) or 0) == 0 and int(stats.get("open_round_trips", 0) or 0) == 0:
        status = "FAIL:ROUND_TRIP_LEDGER_BROKEN"

    report = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "stats": stats,
        "open_round_trips": int(stats.get("open_round_trips", 0) or 0),
        "closed_round_trips": int(stats.get("closed_round_trips", 0) or 0),
        "accounting_errors": int(stats.get("accounting_errors", 0) or 0),
        "round_trip_accounting": result,
    }
    Path("state/round_trip_repair_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(status)


if __name__ == "__main__":
    main()
