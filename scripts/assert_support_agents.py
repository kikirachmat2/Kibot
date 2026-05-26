#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Iterable


def _run(args: Iterable[str], timeout: int = 8) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        text = f"{proc.stdout}\n{proc.stderr}".strip()
        return proc.returncode == 0, text[-1200:]
    except Exception as exc:
        return False, str(exc)


def main() -> int:
    blockers: list[str] = []

    if not shutil.which("crush"):
        blockers.append("crush_missing")
    else:
        ok, text = _run(["crush", "--help"])
        if not ok or "USAGE" not in text.upper():
            blockers.append("crush_help_failed")

    if not shutil.which("gh"):
        blockers.append("gh_missing")

    if blockers:
        print("ASSERT_SUPPORT_AGENTS_BLOCKED", ",".join(blockers))
        return 1

    print("ASSERT_SUPPORT_AGENTS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
