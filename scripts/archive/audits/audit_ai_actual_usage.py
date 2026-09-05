#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Support.ki_config import STATE_DIR

OUT_FILE = STATE_DIR / "ai_actual_usage_audit.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, (dict, list)) else default
    except Exception:
        return default
    return default


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _age_s(value: Any) -> float:
    dt = _parse_dt(value)
    if dt is None:
        return -1.0
    diff = (datetime.now(timezone.utc) - dt).total_seconds()
    return round(max(0.0, diff), 1)


def _ai_invocations_24h() -> Dict[str, int]:
    counts = {"ki_brain": 0, "sovereign_council": 0, "ai_scout": 0, "coordinator": 0}
    traces: List[dict] = []
    for name in ("ai_decision_trace.json", "ai_patrol.json", "ai_strategy_review.json"):
        payload = _read_json(STATE_DIR / name, {})
        if isinstance(payload, dict):
            traces.append(payload)
    for row in traces:
        if row.get("objective") == "maximize_risk_adjusted_profit_for_boss":
            counts["ai_scout"] += 1
        if str(row.get("support_action") or "").strip():
            counts["ai_scout"] += 1
        if str(row.get("best_action") or "").strip():
            counts["ki_brain"] += 1
        if str(row.get("support_role") or "").lower().startswith("council"):
            counts["sovereign_council"] += 1
        if row.get("provider") or row.get("model") or row.get("api_key_envs"):
            counts["coordinator"] += 1
    return counts


def build_ai_actual_usage_audit() -> Dict[str, Any]:
    inventory = _read_json(STATE_DIR / "ai_system_inventory.json", {})
    ai_trace = _read_json(STATE_DIR / "ai_decision_trace.json", {})
    ai_patrol = _read_json(STATE_DIR / "ai_patrol.json", {})
    ai_review = _read_json(STATE_DIR / "ai_strategy_review.json", {})
    workflow = _read_json(STATE_DIR / "workflow_automation.json", {})
    no_trade = _read_json(STATE_DIR / "no_trade_forensics.json", {})
    strategy_actions = _read_json(STATE_DIR / "strategy_control_actions.json", {})
    council_decisions = _read_json(STATE_DIR / "council_decisions.jsonl", [])
    ai_trace_age = _age_s(ai_trace.get("updated_at"))
    ai_patrol_age = _age_s(ai_patrol.get("updated_at"))
    ai_review_age = _age_s(ai_review.get("updated_at"))
    counts = _ai_invocations_24h()

    dashboard_writes = bool(
        (workflow.get("ai_patrol") or {}).get("support_action")
        or (no_trade.get("ai_support_action") is not None)
        or (inventory.get("summary") or {}).get("active_components", 0)
    )
    forensics_writes = bool(no_trade.get("ai_support_action") or no_trade.get("movement_reason"))
    advisory_last = ai_trace.get("reason") or ai_patrol.get("support_action") or ai_review.get("idle_reason_review") or ""
    advisory_at = ai_patrol.get("updated_at") or ai_trace.get("updated_at") or ai_review.get("updated_at") or ""
    status = "ACTIVE_BUT_NOT_USED"
    if ai_trace_age >= 0 and ai_trace_age < 900 and ai_patrol_age >= 0 and ai_patrol_age < 900 and counts["ai_scout"] > 0:
        status = "USED"
    elif ai_trace_age < 0 and ai_patrol_age < 0 and ai_review_age < 0:
        status = "BROKEN"
    elif ai_trace_age >= 0 or ai_patrol_age >= 0 or ai_review_age >= 0:
        status = "ACTIVE_BUT_NOT_USED"
    if any("error" in str(v).lower() for v in (ai_trace.get("reason"), ai_patrol.get("support_action"), ai_review.get("reason"))):
        status = "DEGRADED"
    if not inventory:
        status = "BROKEN"

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "ollama_active": "ollama" in json.dumps(inventory).lower(),
        "ai_scout_active": True,
        "ki_brain_invocations_24h": counts["ki_brain"],
        "sovereign_council_invocations_24h": counts["sovereign_council"],
        "ai_patrol_fresh": ai_patrol_age >= 0 and ai_patrol_age < 900,
        "last_advisory_at": advisory_at,
        "last_advisory": advisory_last,
        "writes_to_dashboard": dashboard_writes,
        "writes_to_forensics": forensics_writes,
        "can_place_order": False,
        "can_override_gate": False,
        "ai_errors": [row.get("reason") for row in council_decisions if isinstance(row, dict) and row.get("error")][:10],
        "ai_trace_age_s": ai_trace_age,
        "ai_patrol_age_s": ai_patrol_age,
        "ai_review_age_s": ai_review_age,
        "evidence": {
            "ai_decision_trace": ai_trace,
            "ai_patrol": ai_patrol,
            "ai_strategy_review": ai_review,
            "workflow_automation": workflow,
            "no_trade_forensics": no_trade,
            "strategy_control_actions": strategy_actions,
        },
    }
    OUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def main() -> int:
    payload = build_ai_actual_usage_audit()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"OK:AI_ACTUAL_USAGE_AUDITED status={payload.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
