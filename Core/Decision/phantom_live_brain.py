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
    mover = {}
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
    try:
        mover_path = Path(__file__).resolve().parent.parent.parent / "state" / "phantom_capital_mover.json"
        if mover_path.exists():
            mover = json.loads(mover_path.read_text(encoding="utf-8"))
    except Exception:
        mover = {}
    targets = board.get("top_targets", []) if isinstance(board, dict) else []
    best = targets[0] if targets else {}
    balances = board.get("available_balances", {}) if isinstance(board, dict) else {}
    treasury = {}
    try:
        treasury_path = Path(__file__).resolve().parent.parent.parent / "state" / "phantom_treasury.json"
        if treasury_path.exists():
            treasury = json.loads(treasury_path.read_text(encoding="utf-8"))
    except Exception:
        treasury = {}
    base_idrx_balance = float(treasury.get("base_idrx_balance") or treasury.get("chains", {}).get("base", {}).get("normalized_idrx") or 0.0)
    sol_balance = float(treasury.get("sol_balance") or treasury.get("chains", {}).get("solana", {}).get("sol_balance") or 0.0)
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
    route = str(best.get("route") or "")
    fee_profiles = mover.get("fee_intelligence", {}) if isinstance(mover, dict) else {}
    selected_fee = fee_profiles.get(route, {}) if isinstance(fee_profiles, dict) else {}
    recovery_mode = str(deadline.get("stage") or "").upper() in {"RECOVERY", "PRESSURE"}
    if global_block:
        capital_action = "EXIT_ONLY"
        decision = "EXIT_ONLY"
    else:
        capital_action = "TRADE_ON_CURRENT_CHAIN" if best.get("executor_status") == "EXECUTABLE" else "SCAN_NEXT"
        if base_idrx_balance > 0 and capital_action == "SCAN_NEXT":
            capital_action = "TRADE_ON_CURRENT_CHAIN"
        if recovery_mode and capital_action == "SCAN_NEXT":
            capital_action = "SCAN_NEXT"
        decision = "ENTER" if best.get("recommended_action") == "ENTER" else "SCAN_NEXT"
        if base_idrx_balance > 0 and not best:
            decision = "ENTER"
        if recovery_mode and decision == "SCAN_NEXT" and best:
            decision = "WATCH"
    notes = []
    if best and best.get("reason"):
        notes.append(str(best.get("reason")))
    if global_reason:
        notes.append(global_reason)
    if selected_fee:
        notes.append(f"gas_mode={selected_fee.get('gas_mode', 'unknown')}")
        notes.append(f"gas_fee_idr={selected_fee.get('gas_fee_idr', 0)}")
        notes.append(f"gas_floor_idr={selected_fee.get('gas_floor_idr', 0)}")
        if not bool(selected_fee.get("gas_affordable", True)):
            notes.append(str(selected_fee.get("gas_reason") or "gas_fee_unaffordable"))
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
        "status": "BLOCKED_WITH_REASON" if global_block else ("ENTERING" if decision == "ENTER" else "ACTIVE"),
        "balances": balances,
        "top_5_targets": targets[:5],
        "selected_route": route,
        "selected_candidate": best,
        "capital_action": capital_action,
        "decision": decision,
        "size": {"amount_idr": 0 if global_block else int(best.get("volume_or_liquidity") or base_idrx_balance or sol_balance or 0)},
        "fatal_blocker": global_reason if global_block else ("" if best or base_idrx_balance > 0 or sol_balance > 0 else "no_tradable_phantom_balance"),
        "advisory_notes": notes,
        "fee_intelligence": selected_fee,
        "recovery_mode": recovery_mode,
        "deadline_stage": deadline.get("stage"),
        "next_action": "EXIT_ONLY" if global_block else ("TRADE_ON_CURRENT_CHAIN" if base_idrx_balance > 0 and not best else decision),
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
