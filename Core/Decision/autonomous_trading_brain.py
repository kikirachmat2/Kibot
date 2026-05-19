from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
import asyncio

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
    capital_governor = {}
    try:
        gov_path = Path(__file__).resolve().parent.parent.parent / "state" / "capital_governor.json"
        if gov_path.exists():
            capital_governor = json.loads(gov_path.read_text(encoding="utf-8"))
    except Exception:
        capital_governor = {}
    trading_pnl_pct = float(capital_governor.get("trading_pnl_pct", capital_governor.get("daily_pnl_pct", 0.0)) or 0.0)
    trading_pnl_idr = float(capital_governor.get("trading_pnl_idr", capital_governor.get("daily_pnl_idr", 0.0)) or 0.0)
    max_daily_loss_idr = float(capital_governor.get("max_daily_loss_idr", 0.0) or 0.0)
    deadline = DeadlineProfitEnforcer().evaluate_enforcer(
        trading_pnl_pct,
        trading_pnl_idr,
        int((indo.get("minutes_to_midnight") or 60)),
    )
    write_phantom_network_maximizer({})
    daily_risk_remaining_idr = max(0.0, max_daily_loss_idr + trading_pnl_idr)
    sizing = AutonomousSizing().size(
        total_capital_idr=float((indo.get("capital_idr") or phantom.get("available_balances", {}).get("solana_sol_idr") or 0.0)),
        venue_capital_idr=float((indo.get("capital_idr") or 0.0)),
        route_bucket_idr=float((phantom.get("available_balances", {}).get("solana_sol_idr") or 0.0)),
        available_balance_idr=float((phantom.get("available_balances", {}).get("solana_sol_idr") or 0.0)),
        daily_risk_remaining_idr=daily_risk_remaining_idr,
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

    def _candidate_is_enter(c: Dict[str, Any]) -> bool:
        if not isinstance(c, dict):
            return False
        route_status = str(c.get("route_status") or "").upper()
        action = str(c.get("recommended_action") or "").upper()
        return route_status == "EXECUTABLE" and action == "ENTER"

    def _candidate_is_liveable(c: Dict[str, Any]) -> bool:
        if not isinstance(c, dict):
            return False
        route_status = str(c.get("route_status") or "").upper()
        action = str(c.get("recommended_action") or "").upper()
        return route_status == "EXECUTABLE" and action in {"ENTER", "WATCH"}

    selected_engine = ""
    selected_route = ""
    selected_candidate = {}
    reason = ""
    fatal_blockers = []
    advisory_signals = []
    current_best_action = "SCAN_MORE"
    posture = "SEARCHING"

    indo_targets = list(indo.get("top_targets") or [])
    phantom_targets = list(phantom.get("top_targets") or [])

    priority_candidates = []
    priority_candidates.extend(("indodax", c) for c in indo_targets if _candidate_is_enter(c))
    priority_candidates.extend(("phantom", c) for c in phantom_targets if _candidate_is_enter(c))
    if not priority_candidates:
        priority_candidates.extend(("indodax", c) for c in indo_targets if _candidate_is_liveable(c))
        priority_candidates.extend(("phantom", c) for c in phantom_targets if _candidate_is_liveable(c))

    if priority_candidates:
        selected_engine, selected_candidate = max(
            priority_candidates,
            key=lambda pair: (
                float(pair[1].get("entry_score") or pair[1].get("wave_score") or 0.0),
                float(pair[1].get("volume_24h_idr") or pair[1].get("volume_or_liquidity") or 0.0),
                float(pair[1].get("change_24h_pct") or pair[1].get("change_pct") or 0.0),
                1 if pair[0] == "indodax" else 0,
            ),
        )
        selected_route = str(selected_candidate.get("route") or ("indodax" if selected_engine == "indodax" else ""))
        current_best_action = "ENTER"
        posture = "ENTERING"
        reason = str(selected_candidate.get("reason") or "candidate_selected")
        advisory_signals = [
            s for s in [
                "low_confidence" if float(selected_candidate.get("wave_score") or selected_candidate.get("entry_score") or 0) < 5 else "",
                "deadline_pressure" if str(deadline.get("stage") or "") in {"PRESSURE", "AGGRESSIVE_SEARCH", "CLOSING_WINDOW"} else "",
            ] if s
        ]
    elif indo_targets:
        selected_engine = "indodax"
        selected_candidate = indo_targets[0]
        selected_route = "indodax"
        reason = str(indo.get("why_not_trading") or "scan_more")
    elif phantom_targets:
        selected_engine = "phantom"
        selected_candidate = phantom_targets[0]
        selected_route = str(selected_candidate.get("route") or "")
        reason = str(phantom.get("why_empty") or "scan_more")
    else:
        reason = str(indo.get("why_not_trading") or phantom.get("why_empty") or deadline.get("reason") or "scan_more")

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
        "next_action": "ENTER" if selected_candidate and sizing.get("approved", False) else "SCAN_MORE",
        "next_check_seconds": 5,
    })


if __name__ == "__main__":
    async def _run() -> None:
        while True:
            try:
                build_autonomous_trading_brain()
            except Exception:
                pass
            await asyncio.sleep(5)

    asyncio.run(_run())
