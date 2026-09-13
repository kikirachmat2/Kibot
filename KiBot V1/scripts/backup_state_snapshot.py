#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from Core.Support.ki_config import PROJECT_ROOT, STATE_DIR


def main() -> None:
    state_dir = Path(STATE_DIR)
    backup_root = Path(PROJECT_ROOT) / "backups" / "state"
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    dest = backup_root / ts
    dest.mkdir(parents=True, exist_ok=True)
    files = [
        "live_truth.json",
        "capital_governor.json",
        "risk_state.json",
        "no_trade_forensics.json",
        "workflow_automation.json",
        "money_movement_audit.json",
        "net_growth_audit.json",
        "fill_quality_audit.json",
        "strategy_symbol_normalization_audit.json",
        "daily_controls_audit.json",
        "critical_operator_questions.json",
    ]
    copied = []
    for name in files:
        src = state_dir / name
        if src.exists():
            shutil.copy2(src, dest / name)
            copied.append(name)
    snapshots = sorted(backup_root.glob("*"))
    while len(snapshots) > 48:
        old = snapshots.pop(0)
        if old.is_dir():
            shutil.rmtree(old, ignore_errors=True)
    payload = {"updated_at": datetime.now(timezone.utc).isoformat(), "dest": str(dest), "copied": copied, "retained": len(snapshots)}
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("status_marker=OK:STATE_BACKUP_SNAPSHOT")


if __name__ == "__main__":
    main()
