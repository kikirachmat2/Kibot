from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
NO_IDLE_FILE = STATE_DIR / "no_idle_director.json"


def write_no_idle_state(payload: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    NO_IDLE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


class NoIdleDirector:
    def update(self, *, best_route_now: str, best_candidate_now: Dict[str, Any], why_not_trading: str, next_action: str, routes_checked_this_cycle: List[str], approved_candidates: int, rejected_candidates: int, posture: str = "ACTIVE_SEARCHING", next_check_seconds: int = 10) -> Dict[str, Any]:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "objective": "maximize_risk_adjusted_profit_for_boss",
            "system_posture": posture,
            "best_route_now": best_route_now,
            "best_candidate_now": best_candidate_now,
            "why_not_trading": why_not_trading,
            "next_action": next_action,
            "next_check_seconds": int(next_check_seconds),
            "routes_checked_this_cycle": routes_checked_this_cycle,
            "candidates_checked_this_cycle": int(approved_candidates + rejected_candidates),
            "approved_candidates": int(approved_candidates),
            "rejected_candidates": int(rejected_candidates),
        }
        write_no_idle_state(payload)
        return payload
