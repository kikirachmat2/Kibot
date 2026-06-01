#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone

from Core.Support.ki_config import STATE_DIR
from Core.Support.money_movement_audit import load_state_bundle
from Core.Support.growth_audit import audit_phantom_non_movement


def main() -> None:
    bundle = load_state_bundle()
    phantom = audit_phantom_non_movement(bundle)
    trace = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "scanner_targets_exist": bool((bundle.get("phantom_targets", {}) or {}).get("top_targets")),
        "candidates_exist": bool([row for row in bundle.get("candidate_decisions", []) if str(row.get("venue") or "").lower().startswith("phantom")]),
        "tier_evaluated": bool([row for row in bundle.get("candidate_decisions", []) if row.get("tier") or row.get("trade_tier") or row.get("label")]),
        "approved": phantom.get("approved_count_24h", 0),
        "executor_received": bool(bundle.get("phantom_live_brain", {})),
        "quote_pass": bool(phantom.get("quote_ok")),
        "swap_build_pass": bool(phantom.get("swap_build_ok")),
        "submit_blocked_reason": phantom.get("reason") or "",
        "fix_applied": "trace_candidate_handoff",
    }
    path = STATE_DIR / "phantom_candidate_handoff_trace.json"
    path.write_text(json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(trace, indent=2, ensure_ascii=False))
    print("status_marker=OK:PHANTOM_CANDIDATE_HANDOFF_TRACED")


if __name__ == "__main__":
    main()
