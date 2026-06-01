from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from Core.Support.ki_config import STATE_DIR
from Core.Support.risk_truth_reconciler import reconcile_risk_truth

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
    risk_state = _read_json("risk_state.json", {})
    canonical = reconcile_risk_truth(live_truth, governor, risk_state, ai_patrol, workflow)

    no_trade_reason = str(
        workflow.get("current_best_action")
        or governor.get("allow_new_orders_reason")
        or dispatcher.get("reason")
        or "WAIT"
    )
    canonical_state = str(canonical.get("canonical_risk_state") or "UNKNOWN")
    allow_new_orders = bool(canonical.get("allow_new_orders", False))
    blockers = canonical.get("canonical_blockers") if isinstance(canonical.get("canonical_blockers"), list) else []
    advisories = canonical.get("advisory_warnings") if isinstance(canonical.get("advisory_warnings"), list) else []
    ignored = canonical.get("ignored_stale_blockers") if isinstance(canonical.get("ignored_stale_blockers"), list) else []
    reasons = " ".join(
        f"{str(item.get('source') or '')} {str(item.get('reason') or '')}"
        for item in blockers
        if isinstance(item, dict)
    ).lower()
    if canonical_state in {"LOCKED", "EMERGENCY"}:
        classification = "BROKEN_WAIT"
    elif "sol_balance_below_trade_min" in str(dispatcher.get("reason") or "").lower() or "trade_min" in str(dispatcher.get("reason") or "").lower():
        classification = "CAPITAL_BOTTLENECK"
    elif allow_new_orders and not blockers:
        if int(len(target_boards.get("indodax", {}).get("top_targets", []) if isinstance(target_boards.get("indodax"), dict) else [])) == 0 and int(len(target_boards.get("phantom", {}).get("top_targets", []) if isinstance(target_boards.get("phantom"), dict) else [])) == 0:
            classification = "STRATEGY_NO_EDGE"
        else:
            classification = "HEALTHY_WAIT"
    elif not allow_new_orders and "orders_disabled" in reasons:
        classification = "CAPITAL_BOTTLENECK"
    elif blockers:
        classification = "BROKEN_WAIT"
    else:
        classification = "HEALTHY_WAIT"
    open_positions = live_truth.get("open_positions") if isinstance(live_truth.get("open_positions"), list) else []
    dust_positions = live_truth.get("dust_positions") if isinstance(live_truth.get("dust_positions"), list) else []

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "classification": classification,
        "canonical_risk_state": canonical_state,
        "movement_status": (
            "LOCKED"
            if canonical_state in {"LOCKED", "EMERGENCY"}
            else ("MICRO_PROBE_ALLOWED" if any("micro" in str(item.get("reason") or "").lower() for item in advisories if isinstance(item, dict)) else ("ACTIVE" if allow_new_orders else "WAITING_FOR_A_PLUS"))
        ),
        "movement_reason": (
            canonical.get("reason")
            or no_trade_reason
            or "movement determined by canonical risk truth"
        ),
        "why_wait": no_trade_reason,
        "canonical_blockers": blockers,
        "advisory_warnings": advisories,
        "ignored_stale_blockers": ignored,
        "inconsistencies": canonical.get("inconsistencies", []) if isinstance(canonical.get("inconsistencies"), list) else [],
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
        "micro_probe": {
            "enabled": bool(_read_json("capital_governor.json", {}).get("micro_probe_enabled", False) or False),
            "remaining_today": int(_read_json("capital_governor.json", {}).get("micro_probe_remaining_today", 0) or 0),
            "last_probe": _read_json("capital_governor.json", {}).get("last_micro_probe", None),
            "last_probe_result": _read_json("capital_governor.json", {}).get("last_micro_probe_result", None),
        },
        "trade_tiers_24h": _read_json("trade_tiers_24h.json", {"a_plus_seen": 0, "micro_probe_seen": 0, "micro_probe_approved": 0, "rejected": 0}),
        "next_action": str(workflow.get("current_best_action") or "WAIT"),
        "what_to_fix": "canonical risk truth reconciled; inspect only if canonical_blockers non-empty or stale state detected",
    }

    FORENSICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    FORENSICS_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload
