from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from Core.Decision.indodax_target_board import build_indodax_target_board
from Core.Intelligence.no_idle_director import write_no_idle_state

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "indodax_live_brain.json"


def write_indodax_live_brain(payload: Dict[str, Any]) -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    resolved = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "indodax",
        "status": "ACTIVE",
        "pairs_checked": 0,
        "top_5_targets": [],
        "selected_candidate": {},
        "decision": "SCAN_NEXT",
        "size_idr": 0,
        "fatal_blocker": "",
        "advisory_notes": [],
        "next_action": "SCAN_NEXT",
        "next_check_seconds": 5,
    }
    resolved.update(payload or {})
    if not resolved.get("next_action"):
        resolved["next_action"] = "SCAN_NEXT"
    STATE_FILE.write_text(json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")
    return resolved


def build_indodax_live_brain() -> Dict[str, Any]:
    board = build_indodax_target_board()
    targets = board.get("top_targets", []) if isinstance(board, dict) else []
    best = targets[0] if targets else {}
    status = "ENTERING" if best and best.get("route_status") == "EXECUTABLE" else "ACTIVE"
    decision = "ENTER" if best and best.get("recommended_action") == "ENTER" else "SCAN_NEXT"
    size_idr = int(best.get("size_idr") or best.get("entry_score") or 0)
    notes = []
    if best and best.get("reason"):
        notes.append(str(best.get("reason")))
    if not best:
        notes.append(str(board.get("why_empty") or "scan_next"))
    write_no_idle_state({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "objective": "maximize_risk_adjusted_profit_for_boss",
        "system_posture": "ENTERING" if decision == "ENTER" else "ACTIVE_SEARCHING",
        "best_route_now": "indodax",
        "best_candidate_now": best,
        "why_not_trading": notes[0] if notes else "",
        "next_action": decision,
        "next_check_seconds": 5,
        "routes_checked_this_cycle": ["indodax"],
        "candidates_checked_this_cycle": len(targets),
        "approved_candidates": len([t for t in targets if t.get("recommended_action") == "ENTER"]),
        "rejected_candidates": len([t for t in targets if t.get("recommended_action") != "ENTER"]),
    })
    return write_indodax_live_brain({
        "status": status,
        "pairs_checked": int(board.get("pairs_checked", 0) or 0),
        "top_5_targets": targets[:5],
        "selected_candidate": best,
        "decision": decision,
        "size_idr": size_idr,
        "fatal_blocker": "",
        "advisory_notes": notes,
        "next_action": decision,
        "next_check_seconds": 5,
    })


async def run_forever() -> None:
    while True:
        try:
            build_indodax_live_brain()
        except Exception:
            pass
        await asyncio.sleep(5)


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
