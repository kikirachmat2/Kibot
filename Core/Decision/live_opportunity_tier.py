from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from Core.Support.churn_guard import evaluate_churn_guard
from Core.Support.strategy_control_actions import build_strategy_control_actions


@dataclass
class LiveOpportunityTierResult:
    tier: str
    approved: bool
    reason: str
    size_idr: float
    constraints: List[str]
    label: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "approved": self.approved,
            "reason": self.reason,
            "size_idr": self.size_idr,
            "constraints": self.constraints,
            "label": self.label,
        }


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", False):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, "", False):
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)


def classify_live_opportunity(candidate: Dict[str, Any], ev: Dict[str, Any], sim: Dict[str, Any], risk: Dict[str, Any], venue_state: Dict[str, Any], config: Dict[str, Any]) -> LiveOpportunityTierResult:
    candidate = candidate if isinstance(candidate, dict) else {}
    ev = ev if isinstance(ev, dict) else {}
    sim = sim if isinstance(sim, dict) else {}
    risk = risk if isinstance(risk, dict) else {}
    venue_state = venue_state if isinstance(venue_state, dict) else {}
    config = config if isinstance(config, dict) else {}

    constraints: List[str] = []
    reason = ""
    tier = "REJECT"
    approved = False
    label = "REJECT"
    size_idr = 0.0

    spread = _float(candidate.get("spread_pct"), _float(sim.get("spread_pct"), 0.0))
    slippage = _float(candidate.get("slippage_est_pct"), _float(sim.get("expected_slippage_pct"), 0.0))
    ev_approved = bool(ev.get("approved", False))
    expected_net_edge = _float(candidate.get("expected_net_edge_pct"), _float(ev.get("expected_net_edge_pct"), _float(ev.get("expected_net_pct"), 0.0)))
    sample_size = _int(candidate.get("historical_sample_size"), _int(ev.get("sample_size"), 0))
    min_trade = max(_float(candidate.get("min_trade_idr"), 0.0), _float(config.get("min_trade_idr"), 10_000.0))
    max_trade = _float(config.get("max_trade_idr"), _float(candidate.get("max_trade_idr"), 0.0))
    daily_loss_ok = not bool(risk.get("daily_loss_breached", False))
    venue_ok = str(venue_state.get("status") or venue_state.get("risk_state") or "OK").upper() not in {"LOCKED", "EMERGENCY", "BLOCKED"}
    exit_plan_valid = bool(candidate.get("exit_plan_valid", True))
    min_sellable = bool(sim.get("min_sellable_pass", False))
    exit_depth = bool(sim.get("exit_depth_pass", False))
    sim_pass = str(sim.get("simulation_verdict") or "").upper() == "PASS"
    pair_quarantined = bool(candidate.get("pair_quarantine"))
    dust_risk = bool(candidate.get("dust_risk", False))
    micro_enabled = bool(config.get("micro_probe_enabled", False))
    micro_size_min = max(min_trade, _float(config.get("micro_probe_min_size_idr"), 10_000.0))
    micro_size_max = _float(config.get("micro_probe_max_size_idr"), 15_000.0)
    micro_per_day_left = max(0, _int(config.get("micro_probe_remaining_today"), 0))
    a_plus_min_sample = _int(config.get("a_plus_min_ev_sample_size"), 20)
    a_plus_min_edge = _float(config.get("a_plus_min_net_edge_pct"), 1.2)
    micro_spread = _float(config.get("micro_probe_max_spread_pct"), 0.6)
    micro_slippage = _float(config.get("micro_probe_max_slippage_pct"), 0.8)
    churn = evaluate_churn_guard({"net_growth_audit": config.get("net_growth_audit") or {}, "capital_governor": risk})
    flat_churn = str(churn.get("net_growth_status") or "").upper() == "FLAT_CHURN"
    control_actions = build_strategy_control_actions({"strategy_edge_audit": config.get("strategy_edge_audit") or {}})
    disabled_pairs = {str(p).upper() for p in control_actions.get("disabled_pairs", [])}
    do_not_scale_pairs = {str(p).upper() for p in control_actions.get("do_not_scale_pairs", [])}
    micro_probe_watchlist = {str(p).upper() for p in control_actions.get("micro_probe_pairs", [])}
    pair = str(candidate.get("pair") or candidate.get("symbol") or "").upper()

    if not daily_loss_ok:
        constraints.append("daily_loss_breached")
        return LiveOpportunityTierResult("REJECT", False, "DAILY_LOSS_LOCK", 0.0, constraints, "REJECT")
    if not venue_ok:
        constraints.append("venue_locked")
        return LiveOpportunityTierResult("REJECT", False, "VENUE_LOCKED", 0.0, constraints, "REJECT")
    if pair_quarantined:
        constraints.append("pair_quarantined")
        return LiveOpportunityTierResult("REJECT", False, "PAIR_QUARANTINED", 0.0, constraints, "REJECT")
    if dust_risk:
        constraints.append("dust_risk")
        return LiveOpportunityTierResult("REJECT", False, "DUST_RISK", 0.0, constraints, "REJECT")
    if pair in disabled_pairs:
        constraints.append("PAIR_DISABLED_NEGATIVE_EDGE")
        return LiveOpportunityTierResult("REJECT", False, "PAIR_DISABLED_NEGATIVE_EDGE", 0.0, constraints, "REJECT")
    if pair in do_not_scale_pairs and expected_net_edge > 0 and sample_size < a_plus_min_sample:
        constraints.append("UNKNOWN_SOURCE_SCALEUP_IGNORED")
    if pair in micro_probe_watchlist and micro_enabled and micro_per_day_left <= 0:
        constraints.append("MICRO_PROBE_WATCHLIST_LIMIT")
    if not sim_pass:
        constraints.append("simulation_failed")
        return LiveOpportunityTierResult("REJECT", False, "PRETRADE_SIM_FAILED", 0.0, constraints, "REJECT")
    if not min_sellable:
        constraints.append("min_sellable_failed")
        return LiveOpportunityTierResult("REJECT", False, "MIN_SELLABLE_FAILED", 0.0, constraints, "REJECT")
    if not exit_depth:
        constraints.append("exit_depth_failed")
        return LiveOpportunityTierResult("REJECT", False, "EXIT_DEPTH_FAILED", 0.0, constraints, "REJECT")
    if not exit_plan_valid:
        constraints.append("exit_plan_invalid")
        return LiveOpportunityTierResult("REJECT", False, "NO_VALID_EXIT_PLAN", 0.0, constraints, "REJECT")
    if spread > float(config.get("max_spread_pct", 1.0) or 1.0):
        constraints.append("spread_too_wide")
        return LiveOpportunityTierResult("REJECT", False, "SPREAD_TOO_WIDE", 0.0, constraints, "REJECT")
    if slippage > float(config.get("max_slippage_pct", 1.2) or 1.2):
        constraints.append("slippage_too_high")
        return LiveOpportunityTierResult("REJECT", False, "SLIPPAGE_TOO_HIGH", 0.0, constraints, "REJECT")
    if expected_net_edge <= 0:
        constraints.append("edge_not_positive")
        return LiveOpportunityTierResult("REJECT", False, "EDGE_NOT_POSITIVE", 0.0, constraints, "REJECT")

    if ev_approved and sample_size >= a_plus_min_sample and expected_net_edge >= a_plus_min_edge:
        tier = "A_PLUS"
        approved = True
        label = "LIVE_A_PLUS"
        size_idr = min(max_trade or micro_size_max, max(min_trade, _float(candidate.get("size_idr"), micro_size_max)))
        reason = "A_PLUS_APPROVED"
        return LiveOpportunityTierResult(tier, approved, reason, round(size_idr, 2), constraints, label)

    if micro_enabled and micro_per_day_left > 0 and not flat_churn:
        if expected_net_edge > 0 and sample_size < a_plus_min_sample and spread <= micro_spread and slippage <= micro_slippage and min_sellable and exit_depth and exit_plan_valid:
            tier = "MICRO_PROBE"
            approved = True
            label = "LIVE_MICRO_PROBE"
            size_idr = min(micro_size_max, max(micro_size_min, _float(candidate.get("size_idr"), micro_size_min)))
            if max_trade > 0:
                size_idr = min(size_idr, max_trade)
            reason = "MICRO_PROBE_APPROVED"
            return LiveOpportunityTierResult(tier, approved, reason, round(size_idr, 2), constraints, label)

    if not ev_approved and sample_size < a_plus_min_sample:
        constraints.append("insufficient_history")
        return LiveOpportunityTierResult("REJECT", False, "INSUFFICIENT_HISTORY", 0.0, constraints, "REJECT")

    constraints.append("not_enough_edge")
    return LiveOpportunityTierResult("REJECT", False, "A_PLUS_NOT_MET", 0.0, constraints, "REJECT")
