#!/usr/bin/env python3
from __future__ import annotations

import json

from Core.Support.money_movement_audit import load_state_bundle
from Core.Support.strategy_control_actions import build_strategy_control_actions


def main() -> None:
    result = build_strategy_control_actions(load_state_bundle())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("status_marker=OK:STRATEGY_CONTROL_ACTIONS_BUILT")


if __name__ == "__main__":
    main()
