from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "autonomous_trading_brain.json"


def write_autonomous_trading_brain(payload: Dict[str, Any]) -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    resolved = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "LIVE_AUTONOMOUS_TRADING",
        "objective": "maximize_risk_adjusted_profit_for_boss",
        "posture": "SEARCHING",
        "current_best_action": "SCAN_MORE",
        "selected_engine": "",
        "selected_route": "",
        "selected_candidate": {},
        "sizing": {},
        "fatal_blockers": [],
        "advisory_signals": [],
        "reason": "",
        "next_action": "SCAN_MORE",
        "next_check_seconds": 5,
    }
    resolved.update(payload or {})
    if not resolved.get("next_action"):
        resolved["next_action"] = "SCAN_MORE"
    STATE_FILE.write_text(json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")
    return resolved


def build_autonomous_trading_brain() -> Dict[str, Any]:
    from Core.Decision.indodax_target_board import build_indodax_target_board
    from Core.Decision.phantom_target_board import build_phantom_target_board
    from Core.Decision.deadline_profit_enforcer import DeadlineProfitEnforcer
    from Core.Treasury.phantom_network_maximizer import write_phantom_network_maximizer
    from Core.Trading.autonomous_sizing import AutonomousSizing

    indo = build_indodax_target_board()
    phantom = build_phantom_target_board()
    deadline = DeadlineProfitEnforcer().evaluate_enforcer(
        float((indo.get("daily_pnl_pct") or 0.0)),
        float((indo.get("daily_pnl_idr") or 0.0)),
        int((indo.get("minutes_to_midnight") or 60)),
    )
    write_phantom_network_maximizer({})
    sizing = AutonomousSizing().size(
        total_capital_idr=float((indo.get("capital_idr") or phantom.get("available_balances", {}).get("solana_sol_idr") or 0.0)),
        venue_capital_idr=float((indo.get("capital_idr") or 0.0)),
        route_bucket_idr=float((phantom.get("available_balances", {}).get("solana_sol_idr") or 0.0)),
        available_balance_idr=float((phantom.get("available_balances", {}).get("solana_sol_idr") or 0.0)),
        daily_risk_remaining_idr=float((deadline.get("daily_pnl_idr") or 0.0)),
        liquidity_usd=float((phantom.get("top_targets") or [{}])[0].get("volume_or_liquidity") or 0.0 if phantom.get("top_targets") else 0.0),
        slippage_pct=1.0,
        confidence=float((phantom.get("top_targets") or [{}])[0].get("wave_score") or 0.0 if phantom.get("top_targets") else 0.0) / 100.0,
        ev_pct=float((indo.get("top_targets") or [{}])[0].get("entry_score") or 0.0 if indo.get("top_targets") else 0.0),
        volatility_pct=1.0,
        current_open_exposure_idr=0.0,
        exit_available=True,
        route=str((phantom.get("top_targets") or [{}])[0].get("route") or "indodax"),
        reserve_locked=True,
        hard_cap_idr=0.0,
    )

    selected_engine = "phantom" if phantom.get("top_targets") else "indodax"
    selected_route = ""
    selected_candidate = {}
    reason = ""
    fatal_blockers = []
    advisory_signals = []
    current_best_action = "SCAN_MORE"
    posture = "SEARCHING"

    if selected_engine == "phantom" and phantom.get("top_targets"):
        selected_candidate = phantom["top_targets"][0]
        selected_route = str(selected_candidate.get("route") or "")
    elif indo.get("top_targets"):
        selected_candidate = indo["top_targets"][0]
        selected_route = "indodax"

    if selected_candidate:
        current_best_action = "ENTER"
        posture = "ENTERING"
        reason = str(selected_candidate.get("reason") or "candidate_selected")
        advisory_signals = [
            s for s in [
                "low_confidence" if float(selected_candidate.get("wave_score") or selected_candidate.get("entry_score") or 0) < 5 else "",
                "deadline_pressure" if str(deadline.get("stage") or "") in {"PRESSURE", "AGGRESSIVE_SEARCH", "CLOSING_WINDOW"} else "",
            ] if s
        ]
    else:
        reason = str(indo.get("why_not_trading") or phantom.get("why_empty") or deadline.get("reason") or "scan_more")
        current_best_action = "SCAN_MORE"
        posture = "SEARCHING"

    return write_autonomous_trading_brain({
        "posture": posture,
        "current_best_action": current_best_action,
        "selected_engine": selected_engine,
        "selected_route": selected_route,
        "selected_candidate": selected_candidate,
        "sizing": sizing,
        "fatal_blockers": fatal_blockers,
        "advisory_signals": advisory_signals,
        "reason": reason,
        "next_action": "ENTER" if selected_candidate else "SCAN_MORE",
        "next_check_seconds": 5,
    })


if __name__ == "__main__":
    print(json.dumps(build_autonomous_trading_brain(), indent=2, ensure_ascii=False))
