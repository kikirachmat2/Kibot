#!/usr/bin/env python3
from __future__ import annotations

import json

from Core.Support.money_movement_audit import load_state_bundle, server_support_audit


def main() -> None:
    result = server_support_audit(load_state_bundle())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"server_support_status={result.get('server_support_status')}")
    print("status_marker=OK:SERVER_SUPPORT_AUDITED")


if __name__ == "__main__":
    main()
