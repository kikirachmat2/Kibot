#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    candidate_files = [ROOT / "Core" / "Exchange" / "jupiter_gateway.py"]
    for file in candidate_files:
        if not file.exists():
            print(f"FAIL:missing:{file.name}")
            return 1

    diag = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "diagnose_phantom_runtime.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    if diag.stdout:
        print(diag.stdout.strip())
    if diag.returncode == 0:
        return 0

    # Preserve the diagnostic code in a concise assert style for healthchecks.
    tail = diag.stdout.strip().splitlines()[-1] if diag.stdout.strip() else "FAIL:PHANTOM_RUNTIME_ERROR"
    if tail.startswith("OK:PHANTOM_LOCKED_MISSING_ENV"):
        return 0
    print(tail)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
