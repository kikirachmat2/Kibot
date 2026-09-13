from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import os

from Core.Support.round_trip_accounting import build_round_trip_accounting


def test_round_trip_accounting_writes_summary(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("Core.Support.round_trip_accounting.STATE_DIR", tmp_path)
    result = build_round_trip_accounting(
        {
            "trade_history": [
                {"venue": "indodax", "pair": "EDEN/IDR", "side": "BUY", "status": "FILLED", "amount_idr": 10000, "timestamp_wib": "2026-06-02T00:00:00+00:00"},
                {"venue": "indodax", "pair": "EDEN/IDR", "side": "SELL", "status": "FILLED", "amount_idr": 11000, "net_realized_pnl_idr": 900, "fee_idr": 100, "timestamp_wib": "2026-06-02T00:10:00+00:00"},
            ]
        }
    )
    assert result["stats"]["closed_round_trips"] == 1


def test_repair_round_trip_ledger_script_emits_status() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/repair_round_trip_ledger.py"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "."},
        check=True,
    )
    assert "ROUND_TRIP_LEDGER" in result.stdout
    assert Path("state/round_trip_repair_report.json").exists()
