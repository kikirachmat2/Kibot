#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from Core.Support.money_movement_audit import load_state_bundle, money_movement_status


def main() -> None:
    result = money_movement_status(load_state_bundle())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"money_movement_status={result['money_movement_status']}")
    print(f"primary_reason={result['primary_reason']}")
    print(f"status_marker=OK:MONEY_MOVEMENT_AUDITED")


if __name__ == "__main__":
    main()
