from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from Core.Support.runtime_mode_guard import assert_runtime_live_only


@dataclass
class DecisionGateResult:
    approved: bool
    reason: str
    hard_rejects: List[str] = field(default_factory=list)
    advisory_notes: List[str] = field(default_factory=list)
    size_modifier: float = 1.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "hard_rejects": self.hard_rejects,
            "advisory_notes": self.advisory_notes,
            "size_modifier": self.size_modifier,
            "details": self.details,
        }


def evaluate_live_trade(candidate: Dict[str, Any], *, runtime_state: Dict[str, Any] | None = None) -> DecisionGateResult:
    assert_runtime_live_only()
    runtime_state = runtime_state or {}
    hard_rejects: List[str] = []
    advisory: List[str] = []

    if str(runtime_state.get("risk_state") or "").upper() in {"EMERGENCY", "LOCKED"}:
        hard_rejects.append("RISK_LOCKED")

    ev = candidate.get("ev_analysis") or {}
    if not bool(ev.get("approved", False)):
        hard_rejects.append("EV_NOT_APPROVED")

    sim = candidate.get("pretrade_simulation") or {}
    if str(sim.get("simulation_verdict") or "").upper() != "PASS":
        hard_rejects.append("PRETRADE_SIM_FAILED")
    if not bool(sim.get("min_sellable_pass", False)):
        hard_rejects.append("MIN_SELLABLE_FAILED")
    if not bool(sim.get("partial_tp_feasible", False)):
        hard_rejects.append("PARTIAL_TP_NOT_FEASIBLE")
    if not bool(sim.get("exit_depth_pass", True)):
        hard_rejects.append("EXIT_DEPTH_FAILED")

    edge = float(candidate.get("expected_net_edge_pct") or ev.get("expected_net_edge_pct") or 0.0)
    min_edge = float(candidate.get("min_net_edge_pct") or 1.5)
    if edge <= 0:
        hard_rejects.append("EDGE_NOT_POSITIVE")
    elif edge < min_edge:
        hard_rejects.append("EDGE_TOO_SMALL_AFTER_COSTS")

    if float(candidate.get("historical_sample_size") or 0) < float(candidate.get("min_ev_sample_size") or 20):
        hard_rejects.append("INSUFFICIENT_HISTORY")

    if str(candidate.get("pair_quarantine") or "").upper() in {"ACTIVE", "BLOCKED"}:
        hard_rejects.append("PAIR_QUARANTINED")

    if float(candidate.get("spread_pct") or 0.0) > float(candidate.get("max_spread_pct") or 1.0):
        hard_rejects.append("SPREAD_TOO_WIDE")
    if float(candidate.get("slippage_est_pct") or 0.0) > float(candidate.get("max_slippage_pct") or 1.2):
        hard_rejects.append("SLIPPAGE_TOO_HIGH")
    if not bool(candidate.get("exit_plan_valid", True)):
        hard_rejects.append("NO_VALID_EXIT_PLAN")

    if float(candidate.get("confidence") or 0.0) < 0.5:
        advisory.append("LOW_CONFIDENCE")
    if float(candidate.get("momentum_score") or 0.0) < 0.5:
        advisory.append("WEAK_MOMENTUM")
    if float(candidate.get("liquidity_score") or 0.0) < 0.5:
        advisory.append("WEAK_LIQUIDITY")

    approved = len(hard_rejects) == 0
    reason = "APPROVED" if approved else hard_rejects[0]
    size_modifier = 1.0
    if advisory and approved:
        size_modifier = 0.7
    if not approved:
        size_modifier = 0.0

    return DecisionGateResult(
        approved=approved,
        reason=reason,
        hard_rejects=hard_rejects,
        advisory_notes=advisory,
        size_modifier=size_modifier,
        details={
            "edge_pct": edge,
            "min_edge_pct": min_edge,
            "ev_approved": bool(ev.get("approved", False)),
            "simulation_verdict": sim.get("simulation_verdict"),
        },
    )

