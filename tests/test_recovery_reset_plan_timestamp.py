from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import os


def test_recovery_reset_plan_has_timestamp() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/assert_recovery_reset_plan.py"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "."},
        check=True,
    )
    assert "OK:RECOVERY_RESET_PLAN" in result.stdout
    payload = json.loads(Path("state/recovery_reset_plan.json").read_text())
    assert payload["next_reset_at"]
    datetime.fromisoformat(str(payload["next_reset_at"]).replace("Z", "+00:00"))
    assert payload["timezone"] == "Asia/Jakarta"

