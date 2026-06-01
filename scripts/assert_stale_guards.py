#!/usr/bin/env python3
from __future__ import annotations

from Core.Support.growth_audit import assert_stale_guard_state
from Core.Support.money_movement_audit import load_state_bundle


def main() -> None:
    result = assert_stale_guard_state(load_state_bundle())
    if result.get("fresh"):
        print("OK:STALE_GUARDS_FRESH")
        return
    raise SystemExit("WARN:STALE_GUARDS_STALE")


if __name__ == "__main__":
    main()
