#!/usr/bin/env python3
from __future__ import annotations

import json

from Core.Support.money_movement_audit import ai_support_audit, load_state_bundle


def main() -> None:
    result = ai_support_audit(load_state_bundle())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"ai_health={result.get('ai_health')}")
    print("status_marker=OK:AI_SUPPORT_AUDITED")


if __name__ == "__main__":
    main()
