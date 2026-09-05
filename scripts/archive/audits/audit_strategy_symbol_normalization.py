#!/usr/bin/env python3
from __future__ import annotations

import json

from Core.Support.growth_audit import audit_strategy_symbol_normalization
from Core.Support.money_movement_audit import load_state_bundle


def main() -> None:
    result = audit_strategy_symbol_normalization(load_state_bundle())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("status_marker=OK:STRATEGY_SYMBOL_NORMALIZATION_AUDITED")


if __name__ == "__main__":
    main()
