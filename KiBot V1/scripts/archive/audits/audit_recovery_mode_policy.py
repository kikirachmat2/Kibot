#!/usr/bin/env python3
from __future__ import annotations

from Core.Support.money_movement_audit import load_state_bundle
from Core.Support.recovery_mode_policy import build_recovery_mode_policy


def main() -> None:
    result = build_recovery_mode_policy(load_state_bundle())
    print(f"OK:RECOVERY_MODE_POLICY active={result.get('active')} reason={result.get('reason')}")


if __name__ == "__main__":
    main()
