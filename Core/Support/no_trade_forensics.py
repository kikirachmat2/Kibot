from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from Core.Support.ki_config import STATE_DIR

FORENSICS_FILE = STATE_DIR / "no_trade_forensics.json"


def _read_json(name: str, default: Any) -> Any:
    path = STATE_DIR / name
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, (dict, list)) else default
    except Exception:
        pass
    return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "None", "nan"):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _classify_wait(payload: Dict[str, Any], workflow: Dict[str, Any]) -> str:
    blockers = payload.get("blockers") if isinstance(payload.get("blockers"), list) else []
    if blockers:
        reasons = " ".join(
            f"{str(item.get('source') or '')} {str(item.get('reason') or '')}"
            for item in blockers
            if isinstance(item, dict)
        ).lower()
        if "inactive_services" in reasons or "rpc" in reasons or "telegram" in reasons:
            return "BROKEN_WAIT"
        if "orders_disabled" in reasons or "allow_new_orders" in reasons:
            return "CAPITAL_BOTTLENECK"
        if "no_targets_visible" in reasons:
            return "STRATEGY_NO_EDGE"
        if "daily_rollover_exit_pending" in reasons:
            return "HEALTHY_WAIT"
        return "BROKEN_WAIT"

    money = workflow.get("money_truth") if isinstance(workflow.get("money_truth"), dict) else {}
    total_balance = _safe_float(money.get("total_balance_idr"), 0.0)
    daily_return = _safe_float(money.get("daily_return_idr"), 0.0)
    allow_orders = bool(money.get("allow_new_orders", False))

    if total_balance <= 0:
        return "BROKEN_WAIT"
    if not allow_orders:
        if daily_return < 0:
            return "CAPITAL_BOTTLENECK"
        return "HEALTHY_WAIT"
    return "HEALTHY_WAIT"


def build_no_trade_forensics() -> Dict[str, Any]:
    workflow = _read_json("workflow_automation.json", {})
    live_truth = _read_json("live_truth.json", {})
    governor = _read_json("capital_governor.json", {})
    dispatcher = _read_json("live_order_dispatcher.json", {})
    ai_patrol = _read_json("ai_patrol.json", {})
    target_boards = {
        "indodax": _read_json("indodax_top_targets.json", {}),
        "phantom": _read_json("phantom_top_targets.json", {}),
    }

    no_trade_reason = str(
        workflow.get("current_best_action")
        or governor.get("allow_new_orders_reason")
        or dispatcher.get("reason")
        or "WAIT"
    )
    classification = _classify_wait(workflow, workflow)
    blockers: List[Dict[str, Any]] = workflow.get("blockers") if isinstance(workflow.get("blockers"), list) else []
    open_positions = live_truth.get("open_positions") if isinstance(live_truth.get("open_positions"), list) else []
    dust_positions = live_truth.get("dust_positions") if isinstance(live_truth.get("dust_positions"), list) else []

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "classification": classification,
        "why_wait": no_trade_reason,
        "blockers": blockers,
        "open_positions_count": len(open_positions),
        "dust_positions_count": len(dust_positions),
        "venue_locks": live_truth.get("venue_locks", {}) if isinstance(live_truth, dict) else {},
        "total_balance_idr": _safe_float(workflow.get("money_truth", {}).get("total_balance_idr"), _safe_float(live_truth.get("total_equity_idr"), 0.0)),
        "daily_return_idr": _safe_float(workflow.get("money_truth", {}).get("daily_return_idr"), _safe_float(live_truth.get("net_pnl_today_idr"), 0.0)),
        "daily_return_pct": _safe_float(workflow.get("money_truth", {}).get("daily_return_pct"), 0.0),
        "allow_new_orders": bool(workflow.get("money_truth", {}).get("allow_new_orders", False)),
        "allow_new_orders_reason": str(workflow.get("money_truth", {}).get("allow_new_orders_reason") or ""),
        "dispatcher_reason": str(dispatcher.get("reason") or ""),
        "ai_support_action": str(ai_patrol.get("support_action") or ""),
        "target_counts": {
            "indodax": len(target_boards.get("indodax", {}).get("top_targets", []) if isinstance(target_boards.get("indodax"), dict) else []),
            "phantom": len(target_boards.get("phantom", {}).get("top_targets", []) if isinstance(target_boards.get("phantom"), dict) else []),
        },
        "next_action": str(workflow.get("current_best_action") or "WAIT"),
    }

    FORENSICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    FORENSICS_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload
