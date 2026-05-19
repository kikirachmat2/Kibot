#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    p = Path("state/phantom_top_targets.json")
    if not p.exists():
        print("phantom_top_targets_missing")
        return 1
    payload = json.loads(p.read_text(encoding="utf-8"))
    breakdown = payload.get("source_breakdown", {})
    if not isinstance(breakdown, dict):
        print("source_breakdown_missing")
        return 1
    if not any(breakdown.get(k, {}).get("count", 0) for k in ("solana_jupiter", "solana_meme", "pumpfun_jupiter", "pumpfun_native", "base_swap", "future_web3")):
        print("phantom_diversity_missing_non_polymarket_routes")
        return 1
    print("ASSERT_PHANTOM_TARGET_DIVERSITY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
