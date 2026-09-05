#!/usr/bin/env python3
from __future__ import annotations

import json

from Core.Support.growth_audit import audit_net_growth
from Core.Support.money_movement_audit import load_state_bundle


def main() -> None:
    result = audit_net_growth(load_state_bundle())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("status_marker=OK:NET_GROWTH_AUDITED")


if __name__ == "__main__":
    main()
