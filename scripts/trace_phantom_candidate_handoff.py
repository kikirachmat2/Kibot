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
    phantom_candidates = [row for row in bundle.get("candidate_decisions", []) if str(row.get("venue") or row.get("route") or "").lower().startswith("phantom")]
    phantom_tiered = [row for row in phantom_candidates if row.get("tier") or row.get("trade_tier") or row.get("label")]
    phantom_approved = [row for row in phantom_candidates if bool(row.get("approved")) or str(row.get("tier") or "").upper() in {"A_PLUS", "MICRO_PROBE"}]
    executor_state = bundle.get("phantom_live_brain", {}) if isinstance(bundle.get("phantom_live_brain"), dict) else {}
    break_stage = (
        "TARGET_TO_CANDIDATE"
        if not phantom_candidates else
        "CANDIDATE_TO_TIER"
        if not phantom_tiered else
        "RISK_LOCK_BEFORE_EXECUTOR"
        if str(bundle.get("no_trade_forensics", {}).get("canonical_risk_state") or "").upper() in {"LOCKED", "EMERGENCY"} else
        "EXECUTOR_TO_SUBMIT"
        if not phantom_approved else
        "NONE"
    )
    trace = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "scanner_targets_count": len((bundle.get("phantom_targets", {}) or {}).get("top_targets") or []),
        "candidate_writer_received": len(phantom_candidates),
        "candidate_decisions_written": len(phantom_candidates),
        "tier_classifier_received": len(phantom_candidates),
        "tier_classifier_output": len(phantom_tiered),
        "executor_received": len(phantom_approved),
        "quote_checked": 1 if bool(phantom.get("quote_ok")) else 0,
        "swap_build_checked": 1 if bool(phantom.get("swap_build_ok")) else 0,
        "submit_attempted": 1 if bool(phantom_approved) and bool(phantom.get("quote_ok")) and bool(phantom.get("swap_build_ok")) else 0,
        "break_stage": break_stage,
        "fix_recommendation": (
            "wire phantom targets into candidate writer"
            if break_stage == "TARGET_TO_CANDIDATE" else
            "wire candidate writer into tier classifier"
            if break_stage == "CANDIDATE_TO_TIER" else
            "risk lock is correct; keep submit blocked until daily reset"
            if break_stage == "RISK_LOCK_BEFORE_EXECUTOR" else
            "wire tier classifier into executor submit path"
            if break_stage == "EXECUTOR_TO_SUBMIT" else
            "fix quote / swap build / submit path"
        ),
        "submit_blocked_reason": phantom.get("reason") or "",
        "fix_applied": "trace_candidate_handoff",
    }
    path = STATE_DIR / "phantom_candidate_handoff_trace.json"
    path.write_text(json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(trace, indent=2, ensure_ascii=False))
    print("status_marker=OK:PHANTOM_CANDIDATE_HANDOFF_TRACED")


if __name__ == "__main__":
    main()
