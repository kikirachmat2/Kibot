from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from Core.Decision.indodax_target_board import build_indodax_target_board
from Core.Decision.phantom_target_board import build_phantom_target_board
from Core.Treasury.phantom_capital_mover import write_phantom_capital_mover
from Core.Treasury.phantom_network_maximizer import write_phantom_network_maximizer
from Core.Decision.engine_independence import write_engine_independence
from Core.Scanner.scanner_executor_contract import ScannerExecutorContract

logger = logging.getLogger("TargetBoardRunner")
STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "target_board_runtime.json"


def _read_json(path: Path, default):
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, type(default)) or isinstance(payload, dict) else default
    except Exception:
        pass
    return default


def _venue_engine_state(governor: dict, venue_key: str, source_status: str, source_reason: str) -> dict:
    venues = governor.get("venues", {}) if isinstance(governor, dict) else {}
    venue = venues.get(venue_key, {}) if isinstance(venues, dict) else {}
    allow_orders = bool(venue.get("allow_orders", False))
    venue_status = str(venue.get("status") or "").upper()
    status = "ACTIVE" if source_status == "OK" and allow_orders else "BLOCKED_WITH_REASON"
    reason = str(venue.get("reason") or source_reason or "")
    if not source_status == "OK":
        reason = reason or f"{venue_key}_scanner_source_failed"
    elif not allow_orders:
        reason = reason or f"{venue_key}_orders_blocked"
    return {
        "status": status,
        "scanner": "ACTIVE" if source_status == "OK" else "BLOCKED_WITH_REASON",
        "executor": "ACTIVE" if allow_orders else "BLOCKED_WITH_REASON",
        "allow_orders": allow_orders,
        "reason": reason,
        "source_status": source_status,
        "source_reason": source_reason,
        "venue_status": venue_status,
    }


def _write_runtime(indodax: dict, phantom: dict, error: str = "") -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "loop_interval_seconds": 5,
        "indodax_updated": bool(indodax),
        "phantom_updated": bool(phantom),
        "indodax_count": len(indodax.get("top_targets", []) or []),
        "phantom_count": len(phantom.get("top_targets", []) or []),
        "errors": {"last_error": error} if error else {},
    }
    STATE_FILE.write_text(__import__("json").dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


async def run_forever() -> None:
    while True:
        try:
            indo = build_indodax_target_board()
            ph = build_phantom_target_board()
            ScannerExecutorContract().write_contract_state()
            write_phantom_capital_mover({})
            write_phantom_network_maximizer({})
            governor = _read_json(STATE_DIR / "capital_governor.json", {})
            phantom_brain = _read_json(STATE_DIR / "phantom_live_brain.json", {})
            indodax_state = _venue_engine_state(
                governor,
                "indodax",
                str(indo.get("source_status") or "NO_DATA").upper(),
                str(indo.get("why_empty") or indo.get("no_data_reason") or ""),
            )
            phantom_state = _venue_engine_state(
                governor,
                "phantom",
                str(ph.get("source_status") or "NO_DATA").upper(),
                str(ph.get("why_empty") or ph.get("no_data_reason") or phantom_brain.get("fatal_blocker") or ""),
            )
            write_engine_independence({
                "indodax_engine": indodax_state,
                "phantom_engine": phantom_state,
                "bridge": "ON" if str(governor.get("bridge", "ON")).upper() == "ON" else "OFF",
                "withdrawal": "ON" if str(governor.get("withdrawal", "ON")).upper() == "ON" else "OFF",
            })
            _write_runtime(indo, ph, "")
        except Exception as exc:  # pragma: no cover
            logger.exception("target board refresh failed: %s", exc)
            _write_runtime({}, {}, str(exc))
        await asyncio.sleep(5)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
