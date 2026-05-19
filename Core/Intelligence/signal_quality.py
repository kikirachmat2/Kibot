"""Signal Quality Gate — first line of defence before the EV Engine.

Scores every candidate signal on five dimensions:
  1. Spread quality     – how wide is the quoted spread vs recent median?
  2. Volume confirmation – is volume trending with the price move?
  3. Lead-lag alignment  – does the signal align with the LeadLag alpha reading?
  4. Volatility regime   – is volatility within an executable range?
  5. Data freshness      – how stale is the underlying market data?

Output is a SignalQuality dataclass attached to every candidate before
it reaches ExpectedValueEngine. Signals graded REJECT are discarded
before any order attempt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SignalGrade(str, Enum):
    STRONG = "STRONG"       # All five dims green — full position allowed
    ACCEPTABLE = "ACCEPTABLE"  # 3-4 dims green — reduced position allowed
    MARGINAL = "MARGINAL"   # 2 dims green — live-skip / wait
    REJECT = "REJECT"       # <2 dims green — hard block


@dataclass
class SignalQuality:
    grade: SignalGrade
    score: float                # 0.0 – 1.0 composite
    spread_ok: bool = False
    volume_ok: bool = False
    leadlag_aligned: bool = False
    volatility_ok: bool = False
    data_fresh: bool = False
    details: List[str] = field(default_factory=list)
    evaluated_at: float = field(default_factory=time.time)

    @property
    def is_tradeable(self) -> bool:
        return self.grade in (SignalGrade.STRONG, SignalGrade.ACCEPTABLE)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grade": self.grade.value,
            "score": round(self.score, 3),
            "spread_ok": self.spread_ok,
            "volume_ok": self.volume_ok,
            "leadlag_aligned": self.leadlag_aligned,
            "volatility_ok": self.volatility_ok,
            "data_fresh": self.data_fresh,
            "is_tradeable": self.is_tradeable,
            "details": self.details,
            "evaluated_at": self.evaluated_at,
        }


# ---------------------------------------------------------------------------
# Thresholds — tune these as market microstructure data matures
# ---------------------------------------------------------------------------
_MAX_SPREAD_PCT = 0.008        # 0.8% max acceptable spread
_MIN_VOLUME_RATIO = 0.6        # current vol / median vol — must be >= 0.6
_MAX_DATA_AGE_S = 45.0         # data must be fresher than 45 seconds
_MIN_VOLATILITY_PCT = 0.003    # below 0.3% daily vol → too flat, skip
_MAX_VOLATILITY_PCT = 0.18     # above 18% daily vol → too wild, skip


def evaluate_signal_quality(
    *,
    spread_pct: Optional[float] = None,
    volume_ratio: Optional[float] = None,     # current / median
    leadlag_score: Optional[float] = None,    # from LeadLagAlphaEngine, range [-1, 1]
    daily_volatility_pct: Optional[float] = None,
    data_age_seconds: Optional[float] = None,
) -> SignalQuality:
    """Score a single signal candidate and return a SignalQuality result.

    All parameters are optional — missing values are treated conservatively
    (they count as a failing dimension but do NOT hard-block by themselves).
    """
    details: List[str] = []
    passing_dims = 0

    # --- 1. Spread ---
    spread_ok = False
    if spread_pct is None:
        details.append("spread: unknown — skipped")
    elif spread_pct <= _MAX_SPREAD_PCT:
        spread_ok = True
        passing_dims += 1
        details.append(f"spread: {spread_pct:.4%} ✓")
    else:
        details.append(f"spread: {spread_pct:.4%} too wide (>{_MAX_SPREAD_PCT:.4%})")

    # --- 2. Volume ---
    volume_ok = False
    if volume_ratio is None:
        details.append("volume: unknown — skipped")
    elif volume_ratio >= _MIN_VOLUME_RATIO:
        volume_ok = True
        passing_dims += 1
        details.append(f"volume ratio: {volume_ratio:.2f} ✓")
    else:
        details.append(f"volume ratio: {volume_ratio:.2f} weak (<{_MIN_VOLUME_RATIO})")

    # --- 3. Lead-lag alignment ---
    leadlag_aligned = False
    if leadlag_score is None:
        details.append("leadlag: unknown — skipped")
    elif leadlag_score > 0.05:
        leadlag_aligned = True
        passing_dims += 1
        details.append(f"leadlag score: {leadlag_score:+.3f} bullish ✓")
    elif leadlag_score < -0.05:
        details.append(f"leadlag score: {leadlag_score:+.3f} bearish — not aligned")
    else:
        details.append(f"leadlag score: {leadlag_score:+.3f} neutral — marginal")

    # --- 4. Volatility regime ---
    volatility_ok = False
    if daily_volatility_pct is None:
        details.append("volatility: unknown — skipped")
    elif _MIN_VOLATILITY_PCT <= daily_volatility_pct <= _MAX_VOLATILITY_PCT:
        volatility_ok = True
        passing_dims += 1
        details.append(f"daily vol: {daily_volatility_pct:.2%} ✓")
    elif daily_volatility_pct < _MIN_VOLATILITY_PCT:
        details.append(f"daily vol: {daily_volatility_pct:.2%} too flat")
    else:
        details.append(f"daily vol: {daily_volatility_pct:.2%} too wild (>{_MAX_VOLATILITY_PCT:.0%})")

    # --- 5. Data freshness ---
    data_fresh = False
    if data_age_seconds is None:
        details.append("data age: unknown — skipped")
    elif data_age_seconds <= _MAX_DATA_AGE_S:
        data_fresh = True
        passing_dims += 1
        details.append(f"data age: {data_age_seconds:.0f}s ✓")
    else:
        details.append(f"data age: {data_age_seconds:.0f}s stale (>{_MAX_DATA_AGE_S:.0f}s)")

    # --- Grade ---
    score = passing_dims / 5.0
    if passing_dims >= 5:
        grade = SignalGrade.STRONG
    elif passing_dims >= 3:
        grade = SignalGrade.ACCEPTABLE
    elif passing_dims == 2:
        grade = SignalGrade.MARGINAL
    else:
        grade = SignalGrade.REJECT

    return SignalQuality(
        grade=grade,
        score=score,
        spread_ok=spread_ok,
        volume_ok=volume_ok,
        leadlag_aligned=leadlag_aligned,
        volatility_ok=volatility_ok,
        data_fresh=data_fresh,
        details=details,
    )


def batch_evaluate(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach a `signal_quality` dict to every candidate in place."""
    for c in candidates:
        sq = evaluate_signal_quality(
            spread_pct=c.get("spread_pct"),
            volume_ratio=c.get("volume_ratio"),
            leadlag_score=c.get("leadlag_score"),
            daily_volatility_pct=c.get("daily_volatility_pct"),
            data_age_seconds=c.get("data_age_seconds"),
        )
        c["signal_quality"] = sq.to_dict()
        c["is_tradeable"] = sq.is_tradeable
    return candidates
