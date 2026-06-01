#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from Core.Decision.phantom_target_board import build_phantom_target_board
from Core.Decision.target_board_runner import _write_candidate_decisions


def main() -> None:
    trace_path = Path("state/phantom_candidate_handoff_trace.json")
    candidates_path = Path("state/candidate_decisions.jsonl")
    phantom_board = build_phantom_target_board()
    _write_candidate_decisions(phantom_board)
    subprocess.run([sys.executable, "scripts/trace_phantom_candidate_handoff.py"], check=True)
    if not trace_path.exists():
        raise SystemExit("FAIL:PHANTOM_HANDOFF_TRACE_MISSING")
    if not candidates_path.exists():
        raise SystemExit("FAIL:PHANTOM_CANDIDATE_DECISIONS_MISSING")

    trace = json.loads(trace_path.read_text())
    rows = []
    for line in candidates_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)

    phantom_rows = [row for row in rows if str(row.get("venue") or "").lower() == "phantom"]
    tiered = [row for row in phantom_rows if row.get("tier") or row.get("trade_tier") or row.get("label")]
    executor_ready = [row for row in phantom_rows if bool(row.get("approved")) or str(row.get("tier") or "").upper() in {"A_PLUS", "MICRO_PROBE"}]
    if not phantom_rows:
        raise SystemExit("FAIL:PHANTOM_CANDIDATE_WRITER_EMPTY")
    if not tiered:
        raise SystemExit("FAIL:PHANTOM_TIER_CLASSIFIER_EMPTY")
    if not trace.get("scanner_targets_count", 0):
        raise SystemExit("FAIL:PHANTOM_SCANNER_TARGETS_MISSING")
    if trace.get("break_stage") == "TARGET_TO_CANDIDATE":
        raise SystemExit("FAIL:PHANTOM_TARGET_TO_CANDIDATE_UNSTAGED")
    if trace.get("break_stage") == "CANDIDATE_TO_TIER":
        raise SystemExit("FAIL:PHANTOM_CANDIDATE_TO_TIER_UNSTAGED")
    if trace.get("break_stage") == "EXECUTOR_TO_SUBMIT" and not executor_ready:
        raise SystemExit("FAIL:PHANTOM_EXECUTOR_READY_MISSING")
    if trace.get("break_stage") == "RISK_LOCK_BEFORE_EXECUTOR":
        print("OK:PHANTOM_HANDOFF_PIPELINE locked_before_executor")
        return
    print("OK:PHANTOM_HANDOFF_PIPELINE")


if __name__ == "__main__":
    main()
