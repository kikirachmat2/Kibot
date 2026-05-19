#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"

FILES = [
    "market_wide_wave_candidates.json",
    "pumpfun_candidates.json",
    "pumpfun_wave_candidates.json",
    "base_scanner_state.json",
    "future_web3_scanner_state.json",
    "indodax_scanner_state.json",
    "solana_jupiter_scanner_state.json",
    "solana_meme_scanner_state.json",
    "pumpfun_jupiter_scanner_state.json",
    "pumpfun_native_scanner_state.json",
    "polymarket_scanner_state.json",
]


def read_json(path: Path):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def main() -> int:
    bad = []
    for name in FILES:
        payload = read_json(STATE / name)
        if not payload:
            continue
        candidates = []
        if isinstance(payload, dict):
            for key in ("candidates", "approved_candidates", "best_candidate"):
                val = payload.get(key)
                if isinstance(val, list):
                    candidates.extend(val)
                elif isinstance(val, dict) and val:
                    candidates.append(val)
        elif isinstance(payload, list):
            candidates = payload
        for cand in candidates:
            if not isinstance(cand, dict):
                bad.append((name, "candidate_not_dict"))
                continue
            proof = cand.get("source_proof")
            if not isinstance(proof, dict):
                bad.append((name, f"missing_source_proof:{cand.get('symbol') or cand.get('mint') or ''}"))
                continue
            if not proof.get("proof_ok"):
                bad.append((name, f"invalid_source_proof:{cand.get('symbol') or cand.get('mint') or ''}"))
            if cand.get("route_availability") is True:
                bad.append((name, f"hardcoded_route_true:{cand.get('symbol') or cand.get('mint') or ''}"))
            if cand.get("route_availability") == "VERIFIED" and not proof.get("proof_ok"):
                bad.append((name, f"verified_without_proof:{cand.get('symbol') or cand.get('mint') or ''}"))

    if bad:
        print("ASSERT_REAL_SCANNERS_FAILED")
        for name, reason in bad[:200]:
            print(f"{name}: {reason}")
        return 1

    print("ASSERT_REAL_SCANNERS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
