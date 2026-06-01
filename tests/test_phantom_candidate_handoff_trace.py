from __future__ import annotations

import json
import subprocess
import sys
import os
from pathlib import Path


def test_phantom_candidate_handoff_trace_script_exists() -> None:
    assert Path("scripts/trace_phantom_candidate_handoff.py").exists()


def test_phantom_candidate_handoff_trace_script_outputs_stage_fields() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/trace_phantom_candidate_handoff.py"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "."},
        check=True,
    )
    payload = json.loads(Path("state/phantom_candidate_handoff_trace.json").read_text())
    assert "scanner_targets_count" in payload
    assert "break_stage" in payload
    assert "fix_recommendation" in payload
