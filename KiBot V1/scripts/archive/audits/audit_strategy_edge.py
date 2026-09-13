#!/usr/bin/env python3
from __future__ import annotations

import json

from Core.Support.money_movement_audit import load_state_bundle, strategy_edge_audit


def main() -> None:
    result = strategy_edge_audit(load_state_bundle())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("status_marker=OK:STRATEGY_EDGE_AUDITED")


if __name__ == "__main__":
    main()
