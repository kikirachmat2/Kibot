#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Scanner.source_proof import SourceProof


def main() -> int:
    p = STATE / "indodax_binance_leadlag_scanner.json"
    if not p.exists():
        print("ASSERT_INDO_BINANCE_LEADLAG_SCANNER_FAILED")
        print("leadlag_state_missing")
        return 1

    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("scan_mode") != "BINANCE_TO_INDODAX_LEADLAG":
        print("ASSERT_INDO_BINANCE_LEADLAG_SCANNER_FAILED")
        print("scan_mode_not_leadlag")
        return 1

    if data.get("source_status") not in {"OK", "DEGRADED", "NO_DATA", "SOURCE_FAILED"}:
        print("ASSERT_INDO_BINANCE_LEADLAG_SCANNER_FAILED")
        print("invalid_source_status")
        return 1

    candidates = data.get("leadlag_candidates", []) or []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        if not SourceProof.validate(item.get("source_proof", {})):
            print("ASSERT_INDO_BINANCE_LEADLAG_SCANNER_FAILED")
            print(f"invalid_indodax_source_proof:{item.get('symbol', '')}")
            return 1
        if not SourceProof.validate(item.get("leader_source_proof", {})):
            print("ASSERT_INDO_BINANCE_LEADLAG_SCANNER_FAILED")
            print(f"invalid_binance_source_proof:{item.get('symbol', '')}")
            return 1
        if not item.get("binance_symbol"):
            print("ASSERT_INDO_BINANCE_LEADLAG_SCANNER_FAILED")
            print(f"missing_binance_symbol:{item.get('symbol', '')}")
            return 1

    print("ASSERT_INDO_BINANCE_LEADLAG_SCANNER_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
