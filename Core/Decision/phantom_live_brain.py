from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from Core.Decision.phantom_target_board import build_phantom_target_board
from Core.Treasury.phantom_capital_mover import write_phantom_capital_mover
from Core.Decision.deadline_profit_enforcer import DeadlineProfitEnforcer
from Core.Treasury.capital_governor import GOVERNOR_FILE

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "phantom_live_brain.json"


def write_phantom_live_brain(payload: Dict[str, Any]) -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    resolved = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "phantom",
        "status": "ACTIVE",
        "balances": {},
        "top_5_targets": [],
        "selected_route": "",
        "selected_candidate": {},
        "capital_action": "SCAN_NEXT",
        "decision": "SCAN_NEXT",
        "size": {},
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


def build_phantom_live_brain() -> Dict[str, Any]:
    board = build_phantom_target_board()
    targets = board.get("top_targets", []) if isinstance(board, dict) else []
    best = targets[0] if targets else {}
    balances = board.get("available_balances", {}) if isinstance(board, dict) else {}
    deadline = DeadlineProfitEnforcer().evaluate_enforcer(0.0, 0.0, 999)
    try:
        if GOVERNOR_FILE.exists():
            gov = json.loads(GOVERNOR_FILE.read_text(encoding="utf-8"))
            deadline = DeadlineProfitEnforcer().evaluate_enforcer(
                float(gov.get("daily_pnl_pct", 0.0) or 0.0),
                float(gov.get("daily_pnl_idr", 0.0) or 0.0),
                int(board.get("minutes_to_midnight", 999) if isinstance(board, dict) else 999),
            )
    except Exception:
        pass
    route = str(best.get("route") or "")
    recovery_mode = str(deadline.get("stage") or "").upper() in {"RECOVERY", "PRESSURE"}
    capital_action = "TRADE_ON_CURRENT_CHAIN" if best.get("executor_status") == "EXECUTABLE" else "SCAN_NEXT"
    if recovery_mode and capital_action == "SCAN_NEXT":
        capital_action = "SCAN_NEXT"
    decision = "ENTER" if best.get("recommended_action") == "ENTER" else "SCAN_NEXT"
    if recovery_mode and decision == "SCAN_NEXT" and best:
        decision = "WATCH"
    notes = []
    if best and best.get("reason"):
        notes.append(str(best.get("reason")))
    if not best:
        notes.append(str(board.get("why_empty") or "scan_next"))
    write_phantom_capital_mover({
        "recommended_action": {
            "route": route,
            "action": capital_action,
            "amount_idr": int(best.get("volume_or_liquidity") or 0),
            "reason": str(best.get("reason") or ""),
        },
    })
    return write_phantom_live_brain({
        "status": "ENTERING" if decision == "ENTER" else "ACTIVE",
        "balances": balances,
        "top_5_targets": targets[:5],
        "selected_route": route,
        "selected_candidate": best,
        "capital_action": capital_action,
        "decision": decision,
        "size": {"amount_idr": int(best.get("volume_or_liquidity") or 0)},
        "fatal_blocker": "",
        "advisory_notes": notes,
        "recovery_mode": recovery_mode,
        "deadline_stage": deadline.get("stage"),
        "next_action": decision,
        "next_check_seconds": 5,
    })


async def run_forever() -> None:
    while True:
        try:
            build_phantom_live_brain()
        except Exception:
            pass
        await asyncio.sleep(5)


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
