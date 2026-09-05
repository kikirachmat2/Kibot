#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


def main() -> int:
    path = Path(__file__).resolve().parents[3] / "Core" / "Executors" / "Indodax" / "indodax_executor.py"
    text = path.read_text(encoding="utf-8")
    gate_pos = text.find("evaluate_live_trade(")
    trade_pos = text.find('type=side.lower()')
    if gate_pos < 0:
        print("FAIL:gate_missing")
        return 1
    if trade_pos < 0:
        print("FAIL:trade_call_missing")
        return 1
    if gate_pos > trade_pos:
        print("FAIL:gate_after_trade")
        return 1
    print("OK:INDODAX_LIVE_GATE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
