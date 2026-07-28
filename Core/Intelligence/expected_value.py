"""Expected Value (EV) Engine — mathematical gating before execution.

Formula:
    EV = (win_prob * avg_win_pct) - ((1 - win_prob) * avg_loss_pct)

A trade is only permitted if:
    - EV >= EV_MIN_THRESHOLD (default 0.3%)
    - Kelly fraction (capped) yields position size > 0
    - Reward-to-risk ratio >= MIN_RR_RATIO (default 1.5)

All calculations are deterministic. No external calls. No randomness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time


# ---------------------------------------------------------------------------
# Configuration constants — tune from backtest results
# ---------------------------------------------------------------------------
EV_MIN_THRESHOLD: float = 0.003     # minimum EV (0.3%) to approve a trade
MIN_RR_RATIO: float = 1.5           # minimum reward-to-risk
MAX_KELLY_FRACTION: float = 0.25    # never risk more than 25% of bankroll even if Kelly says more
KELLY_FLOOR: float = 0.01           # minimum Kelly fraction to bother entering
MIN_SAMPLE_SIZE: int = 20


@dataclass
class EVResult:
    approved: bool
    ev_pct: float                   # expected value as a fraction (0.01 = 1%)
    kelly_fraction: float           # recommended position as fraction of bankroll
    rr_ratio: float                 # reward-to-risk ratio
    win_prob: float
    avg_win_pct: float
    avg_loss_pct: float
    rejection_reasons: List[str] = field(default_factory=list)
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "ev_pct": round(self.ev_pct * 100, 4),          # % format
            "kelly_fraction": round(self.kelly_fraction, 4),
            "recommended_position_pct": round(self.kelly_fraction * 100, 2),
            "rr_ratio": round(self.rr_ratio, 3),
            "win_prob": round(self.win_prob, 3),
            "avg_win_pct": round(self.avg_win_pct * 100, 3),
            "avg_loss_pct": round(self.avg_loss_pct * 100, 3),
            "rejection_reasons": self.rejection_reasons,
            "evaluated_at": self.evaluated_at,
        }


def compute_ev(
    *,
    win_prob: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    fee_pct: float = 0.003,         # Indodax taker fee default 0.3%
    slippage_pct: float = 0.001,    # estimate slippage 0.1%
    override_ev_threshold: Optional[float] = None,
    override_rr_threshold: Optional[float] = None,
) -> EVResult:
    """Compute EV and Kelly for a single trade setup.

    Args:
        win_prob: Historical win rate [0.0, 1.0].
        avg_win_pct: Average profit as fraction (e.g. 0.015 = 1.5%).
        avg_loss_pct: Average loss as fraction (positive value, e.g. 0.01 = 1%).
        fee_pct: Round-trip fee fraction.
        slippage_pct: Estimated slippage fraction.
        override_ev_threshold: Override global EV_MIN_THRESHOLD for this call.
        override_rr_threshold: Override global MIN_RR_RATIO for this call.
    """
    rejection_reasons: List[str] = []

    # Clamp inputs to sane ranges
    win_prob = max(0.0, min(1.0, win_prob))
    loss_prob = 1.0 - win_prob
    avg_win_net = max(0.0, avg_win_pct - fee_pct - slippage_pct)
    avg_loss_net = max(0.0001, avg_loss_pct + fee_pct + slippage_pct)

    ev = (win_prob * avg_win_net) - (loss_prob * avg_loss_net)

    rr_ratio = avg_win_net / avg_loss_net if avg_loss_net > 0 else 0.0

    # Kelly Criterion: f* = (bp - q) / b   where b = win/loss ratio, p = win, q = loss
    b = avg_win_net / avg_loss_net if avg_loss_net > 0 else 0
    kelly_raw = ((b * win_prob) - loss_prob) / b if b > 0 else 0.0
    kelly = max(0.0, min(MAX_KELLY_FRACTION, kelly_raw * 0.5))  # half-Kelly for safety

    ev_threshold = override_ev_threshold if override_ev_threshold is not None else EV_MIN_THRESHOLD
    rr_threshold = override_rr_threshold if override_rr_threshold is not None else MIN_RR_RATIO

    approved = True

    if ev < ev_threshold:
        approved = False
        rejection_reasons.append(
            f"EV {ev*100:.3f}% below threshold {ev_threshold*100:.3f}%"
        )
    if rr_ratio < rr_threshold:
        approved = False
        rejection_reasons.append(
            f"R:R {rr_ratio:.2f} below minimum {rr_threshold:.2f}"
        )
    if kelly < KELLY_FLOOR:
        approved = False
        rejection_reasons.append(
            f"Kelly {kelly:.4f} below floor {KELLY_FLOOR:.4f} — not worth entering"
        )
    if win_prob < 0.40:
        rejection_reasons.append(
            f"Win rate {win_prob:.1%} is below 40% — flag for review"
        )

    return EVResult(
        approved=approved,
        ev_pct=ev,
        kelly_fraction=kelly,
        rr_ratio=rr_ratio,
        win_prob=win_prob,
        avg_win_pct=avg_win_net,
        avg_loss_pct=avg_loss_net,
        rejection_reasons=rejection_reasons,
    )


def ev_from_candidate(candidate: Dict[str, Any]) -> EVResult:
    """Convenience wrapper that reads standard candidate dict fields."""
    sample_size = int(candidate.get("historical_sample_size", 0) or candidate.get("sample_size", 0) or 0)
    win_prob = float(candidate.get("win_rate", 0.0) or 0.0)
    avg_win_pct = float(candidate.get("avg_profit_pct", 0.0) or 0.0)
    avg_loss_pct = float(candidate.get("avg_loss_pct", 0.0) or 0.0)
    fee_pct = float(candidate.get("fee_pct", 0.003))
    slippage_pct = float(candidate.get("slippage_pct", 0.001))

    res = compute_ev(
        win_prob=win_prob,
        avg_win_pct=avg_win_pct,
        avg_loss_pct=avg_loss_pct,
        fee_pct=fee_pct,
        slippage_pct=slippage_pct,
    )

    if not candidate.get("is_specific_match", True):
        res.approved = False
        res.rejection_reasons.insert(
            0, "Fallback global stats used — specific strategy/pair historical track record required for live approval"
        )
    elif sample_size < MIN_SAMPLE_SIZE:
        res.approved = False
        res.rejection_reasons.insert(
            0, f"Historical sample size {sample_size} below minimum {MIN_SAMPLE_SIZE}"
        )
    return res


def batch_evaluate_ev(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach EV analysis to each candidate. Marks non-approved ones clearly."""
    for c in candidates:
        result = ev_from_candidate(c)
        c["ev_analysis"] = result.to_dict()
        c["ev_approved"] = result.approved
        # Also stamp recommended position size directly on candidate
        c["kelly_position_pct"] = result.kelly_fraction * 100.0
    return candidates
