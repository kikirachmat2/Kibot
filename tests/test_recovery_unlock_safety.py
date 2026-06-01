from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import os


def test_recovery_unlock_safety_script_runs() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/assert_recovery_unlock_safety.py"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "."},
        check=True,
    )
    assert "OK:RECOVERY_UNLOCK_SAFETY" in result.stdout
    assert Path("state/recovery_reset_plan.json").exists()

