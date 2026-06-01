#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

from Core.Support.ki_config import KiConfig

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"


def _read(path: Path) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def main() -> None:
    runtime_mode = (os.getenv("KIBOT_RUNTIME_MODE") or os.getenv("KIBOT_TRADING_MODE") or getattr(KiConfig, "TRADING_MODE", "")).upper()
    if runtime_mode != "LIVE_ONLY":
        raise SystemExit(f"FAIL:runtime_mode={runtime_mode}")
    if not (os.getenv("KIBOT_LIVE_OPPORTUNITY_EXPANSION", "").strip().lower() == "true" or bool(getattr(KiConfig, "LIVE_OPPORTUNITY_EXPANSION", False))):
        raise SystemExit("FAIL:live_opportunity_expansion_disabled")
    if os.getenv("KIBOT_FORCE_DAILY_PROFIT", "false").strip().lower() == "true":
        raise SystemExit("FAIL:daily_profit_forced")

    no_trade = _read(STATE / "no_trade_forensics.json")
    if "movement_status" not in no_trade:
        raise SystemExit("FAIL:no_trade_forensics_missing_movement_status")

    print("OK:LIVE_OPPORTUNITY_EXPANSION")


if __name__ == "__main__":
    main()
