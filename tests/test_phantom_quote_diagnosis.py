from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import os


def test_phantom_quote_diagnosis_script_runs() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/diagnose_phantom_quotes.py"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "."},
        check=True,
    )
    assert "status_marker=OK:PHANTOM_QUOTE_DIAGNOSIS" in result.stdout
    payload = json.loads(Path("state/phantom_quote_diagnosis.json").read_text())
    assert "status" in payload
    assert "recommended_fix" in payload

