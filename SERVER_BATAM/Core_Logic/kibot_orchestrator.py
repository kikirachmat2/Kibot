#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import time
from typing import Iterable

WATCHED_UNITS = (
    "kibot-command-center.service",
    "kibot-notifier.service",
    "kibot-guardian.service",
    "kibot-analyst.service",
    "lazarus-ampere.service",
)


def _is_active(unit: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", unit],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _restart(unit: str) -> None:
    subprocess.run(["sudo", "systemctl", "restart", unit], check=False)


def _heal(units: Iterable[str]) -> None:
    for unit in units:
        if not _is_active(unit):
            print(f"[ORCHESTRATOR] restarting {unit}", flush=True)
            _restart(unit)


def main() -> None:
    print("[ORCHESTRATOR] KiBot orchestrator online", flush=True)
    while True:
        try:
            _heal(WATCHED_UNITS)
        except Exception as error:
            print(f"[ORCHESTRATOR][WARN] {error}", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
