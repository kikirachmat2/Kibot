#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    candidate_files = [
        root / "Core" / "Exchange" / "jupiter_gateway.py",
    ]
    for file in candidate_files:
        if not file.exists():
            print(f"FAIL:missing:{file.name}")
            return 1
    rpc = os.getenv("SOLANA_RPC_URL") or os.getenv("KIBOT_SOLANA_RPC_URL")
    pk = os.getenv("PHANTOM_PRIVATE_KEY") or os.getenv("KIBOT_PHANTOM_PRIVATE_KEY")
    enabled = str(os.getenv("KIBOT_PHANTOM_ENABLED", "true")).lower() in {"1", "true", "yes", "on"}
    if not enabled:
        print("OK:PHANTOM_LOCKED_MISSING_ENV")
        return 0
    if not rpc or not pk:
        print("OK:PHANTOM_LOCKED_MISSING_ENV")
        return 0
    print("OK:PHANTOM_LIVE_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

