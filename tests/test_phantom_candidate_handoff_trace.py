from __future__ import annotations

from pathlib import Path


def test_phantom_candidate_handoff_trace_script_exists() -> None:
    assert Path("scripts/trace_phantom_candidate_handoff.py").exists()

