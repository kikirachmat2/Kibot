#!/usr/bin/env python3
from __future__ import annotations

import json

from Core.Support.growth_audit import audit_daily_controls
from Core.Support.money_movement_audit import load_state_bundle


def main() -> None:
    result = audit_daily_controls(load_state_bundle())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("status_marker=OK:DAILY_CONTROLS_AUDITED")


if __name__ == "__main__":
    main()
