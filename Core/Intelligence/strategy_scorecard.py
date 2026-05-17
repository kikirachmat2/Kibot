"""Strategy Scorecard — final aggregation layer before execution gate.

Combines signal quality, EV analysis, market regime, punishment status,
and optional LLM advisory into a single composite score with verdict.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ScorecardVerdict(str, Enum):
    APPROVED = "APPROVED"
    PAPER_ONLY = "PAPER_ONLY"
    REJECTED = "REJECTED"


@dataclass
class ScorecardResult:
    verdict: ScorecardVerdict
    composite_score: float
    signal_score: float
    ev_score: float
    regime_score: float
    punishment_penalty: float
    llm_advisory_delta: float
    breakdown: List[str] = field(default_factory=list)
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "composite_score": round(self.composite_score, 4),
            "signal_score": round(self.signal_score, 4),
            "ev_score": round(self.ev_score, 4),
            "regime_score": round(self.regime_score, 4),
            "punishment_penalty": round(self.punishment_penalty, 4),
            "llm_advisory_delta": round(self.llm_advisory_delta, 4),
            "breakdown": self.breakdown,
            "evaluated_at": self.evaluated_at,
        }


APPROVE_THRESHOLD = 0.62
PAPER_THRESHOLD = 0.42
_W_SIGNAL, _W_EV, _W_REGIME, _W_PUNISHMENT = 0.30, 0.35, 0.20, 0.15


def score_candidate(
    *,
    signal_quality_dict: Optional[Dict[str, Any]] = None,
    ev_analysis_dict: Optional[Dict[str, Any]] = None,
    market_regime: Optional[str] = None,
    quarantine_active: bool = False,
    punishment_severity: float = 0.0,
    llm_advisory_score: Optional[float] = None,
) -> ScorecardResult:
    breakdown: List[str] = []

    sq = signal_quality_dict or {}
    _grade_map = {"STRONG": 1.0, "ACCEPTABLE": 0.7, "MARGINAL": 0.4, "REJECT": 0.0}
    signal_score = _grade_map.get(sq.get("grade", "REJECT"), 0.0)
    breakdown.append(f"signal={signal_score:.2f}")

    ev = ev_analysis_dict or {}
    ev_approved = ev.get("approved", False)
    ev_pct = ev.get("ev_pct", 0.0)
    ev_score = min(1.0, 0.5 + (ev_pct / 3.0)) if ev_approved else max(0.0, 0.3 + (ev_pct / 10.0))
    breakdown.append(f"ev({'ok' if ev_approved else 'no'},{ev_pct:.3f}%)={ev_score:.2f}")

    regime = (market_regime or "UNKNOWN").upper()
    regime_score = {"BULL": 0.9, "RANGING": 0.7, "VOLATILE": 0.5, "BEAR": 0.3}.get(regime, 0.5)
    breakdown.append(f"regime({regime})={regime_score:.2f}")

    if quarantine_active:
        punishment_penalty = 1.0
        breakdown.append("quarantine=ACTIVE")
    else:
        punishment_penalty = min(1.0, max(0.0, punishment_severity))
        breakdown.append(f"punishment={punishment_penalty:.2f}")

    llm_delta = max(-0.15, min(0.15, (llm_advisory_score or 0.0) * 0.15))
    if llm_advisory_score is not None:
        breakdown.append(f"llm={llm_delta:+.3f}")

    base = (_W_SIGNAL * signal_score + _W_EV * ev_score
            + _W_REGIME * regime_score - _W_PUNISHMENT * punishment_penalty)
    composite = max(0.0, min(1.0, base + llm_delta))
    breakdown.append(f"composite={composite:.4f}")

    if quarantine_active:
        verdict = ScorecardVerdict.REJECTED
    elif composite >= APPROVE_THRESHOLD:
        verdict = ScorecardVerdict.APPROVED
    elif composite >= PAPER_THRESHOLD:
        verdict = ScorecardVerdict.PAPER_ONLY
    else:
        verdict = ScorecardVerdict.REJECTED

    breakdown.append(f"→ {verdict.value}")
    return ScorecardResult(
        verdict=verdict, composite_score=composite, signal_score=signal_score,
        ev_score=ev_score, regime_score=regime_score, punishment_penalty=punishment_penalty,
        llm_advisory_delta=llm_delta, breakdown=breakdown,
    )


def run_scorecard(candidate: Dict[str, Any], *, market_regime: str = "UNKNOWN") -> Dict[str, Any]:
    result = score_candidate(
        signal_quality_dict=candidate.get("signal_quality"),
        ev_analysis_dict=candidate.get("ev_analysis"),
        market_regime=market_regime,
        quarantine_active=candidate.get("quarantine_active", False),
        punishment_severity=candidate.get("punishment_severity", 0.0),
        llm_advisory_score=candidate.get("llm_advisory_score"),
    )
    candidate["scorecard"] = result.to_dict()
    candidate["scorecard_verdict"] = result.verdict.value
    return candidate
