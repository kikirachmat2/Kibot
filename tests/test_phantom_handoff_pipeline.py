from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import os


def test_phantom_handoff_pipeline_script_exists() -> None:
    assert Path("scripts/assert_phantom_handoff_pipeline.py").exists()


def test_phantom_handoff_pipeline_runs() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/assert_phantom_handoff_pipeline.py"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "."},
        check=True,
    )
    assert "OK:PHANTOM_HANDOFF_PIPELINE" in result.stdout

