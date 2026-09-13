from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from Core.Decision.indodax_target_board import build_indodax_target_board
from Core.Intelligence.no_idle_director import write_no_idle_state
from Core.Decision.deadline_profit_enforcer import DeadlineProfitEnforcer
from Core.Treasury.capital_governor import GOVERNOR_FILE

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
    pnl_reconciliation = {}
    try:
        import signal

        def _timeout_handler(signum, frame):
            raise TimeoutError("reconcile_pnl_state timed out after 30s")

        from Core.Treasury.pnl_reconciliation import reconcile_pnl_state

        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(30)
        try:
            pnl_reconciliation = reconcile_pnl_state(write=True)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    except Exception:
        pnl_reconciliation = {}
    targets = board.get("top_targets", []) if isinstance(board, dict) else []
    best = targets[0] if targets else {}
    governor = {}
    global_block = False
    global_reason = ""
    try:
        if GOVERNOR_FILE.exists():
            governor = json.loads(GOVERNOR_FILE.read_text(encoding="utf-8"))
            global_block = not bool(governor.get("allow_new_orders", False)) or str(governor.get("status") or "").upper() == "BLOCKED_WITH_REASON"
            global_reason = str(governor.get("allow_new_orders_reason") or "").strip()
    except Exception:
        governor = {}
    if not global_reason and global_block:
        global_pnl = float(governor.get("daily_pnl_idr", 0.0) or 0.0)
        global_cap = float(governor.get("max_daily_loss_idr", 0.0) or 0.0)
        if global_cap > 0:
            global_reason = f"global_daily_loss_cap_breached ({global_pnl:.2f} <= -{global_cap:.2f})"
        else:
            global_reason = "capital_governor_global_block"
    deadline = DeadlineProfitEnforcer().evaluate_enforcer(0.0, 0.0, 999)
    try:
        if governor:
            deadline = DeadlineProfitEnforcer().evaluate_enforcer(
                float(governor.get("daily_pnl_pct", 0.0) or 0.0),
                float(governor.get("daily_pnl_idr", 0.0) or 0.0),
                int(board.get("minutes_to_midnight", 999) if isinstance(board, dict) else 999),
            )
    except Exception:
        pass
    recovery_mode = str(deadline.get("stage") or "").upper() in {"RECOVERY", "PRESSURE"}
    if global_block:
        status = "BLOCKED_WITH_REASON"
        decision = "EXIT_ONLY"
    else:
        status = "ENTERING" if best and best.get("route_status") == "EXECUTABLE" else ("RECOVERY" if recovery_mode else "ACTIVE")
        decision = "ENTER" if best and best.get("recommended_action") == "ENTER" else ("SCAN_NEXT" if not recovery_mode else "ROTATE")
    size_idr = 0 if global_block else int(best.get("size_idr") or best.get("entry_score") or 0)
    notes = []
    if best and best.get("reason"):
        notes.append(str(best.get("reason")))
    if global_reason:
        notes.append(global_reason)
    if not best:
        notes.append(str(board.get("why_empty") or "scan_next"))
    write_no_idle_state({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "objective": "maximize_risk_adjusted_profit_for_boss",
        "system_posture": "FATAL_BLOCKED" if global_block else ("ENTERING" if decision == "ENTER" else "ACTIVE_SEARCHING"),
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
        "fatal_blocker": global_reason if global_block else "",
        "advisory_notes": notes,
        "what_if_checks": pnl_reconciliation.get("what_if_checks", []) if isinstance(pnl_reconciliation, dict) else [],
        "recovery_mode": recovery_mode,
        "deadline_stage": deadline.get("stage"),
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
