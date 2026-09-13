"""Daily green probability estimator.

This is a calibrated-shape heuristic, not a promise. It carries a quality label
so weak early estimates are never mistaken for certainty.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _sample_quality(sample_size: int) -> str:
    if sample_size < 10:
        return "WEAK"
    if sample_size < 50:
        return "DEVELOPING"
    if sample_size < 100:
        return "USABLE"
    return "STRONG"


def estimate_green_probability(
    *,
    daily_context: Dict[str, Any] | None = None,
    heatmap: Dict[str, Any] | None = None,
    candidates: Iterable[Dict[str, Any]] | None = None,
    order_summary: Dict[str, Any] | None = None,
    system_health: Dict[str, Any] | None = None,
    source_health: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    daily_context = daily_context or {}
    heatmap = heatmap or {}
    order_summary = order_summary or {}
    system_health = system_health or {}
    source_health = source_health or {}
    candidate_list: List[Dict[str, Any]] = [c for c in list(candidates or []) if isinstance(c, dict)]

    score = 0.48
    positives: List[str] = []
    negatives: List[str] = []

    daily_color = str(daily_context.get("daily_color") or "FLAT").upper()
    if daily_color == "GREEN":
        score += 0.16
        positives.append("day already green")
    elif daily_color == "RECOVERY":
        score -= 0.10
        negatives.append("day is in recovery")

    urgency = str(daily_context.get("urgency_level") or "LOW").upper()
    if urgency in {"HIGH", "CRITICAL"} and daily_color != "GREEN":
        score -= 0.08
        negatives.append(f"deadline pressure {urgency.lower()}")
    elif urgency in {"LOW", "NORMAL"}:
        score += 0.03
        positives.append("enough time before deadline")

    breadth = str(heatmap.get("market_breadth") or "UNKNOWN").upper()
    if breadth == "BROAD_RISK_ON":
        score += 0.10
        positives.append("broad Indodax pump regime")
    elif breadth == "SELECTIVE":
        score += 0.05
        positives.append("selective pump regime")
    elif breadth == "RISK_OFF":
        score -= 0.08
        negatives.append("market breadth risk-off")

    grade_a = sum(1 for c in candidate_list if str(c.get("trade_grade") or c.get("entry_quality") or "").upper() == "A")
    grade_b = sum(1 for c in candidate_list if str(c.get("trade_grade") or c.get("entry_quality") or "").upper() == "B")
    if grade_a:
        score += min(0.12, grade_a * 0.06)
        positives.append(f"{grade_a} grade-A candidate(s)")
    if grade_b:
        score += min(0.08, grade_b * 0.03)
        positives.append(f"{grade_b} grade-B candidate(s)")
    if not grade_a and not grade_b:
        score -= 0.08
        negatives.append("no grade-A/B candidate")

    cpu = _f(system_health.get("cpu"))
    ram = _f(system_health.get("ram"))
    disk = _f(system_health.get("disk"))
    if cpu > 95 or ram > 90 or disk > 90:
        score -= 0.10
        negatives.append("server health pressure")
    elif cpu or ram or disk:
        score += 0.02
        positives.append("server health acceptable")

    stale_sources = [k for k, v in source_health.items() if str(v).upper() in {"FAILED", "STALE", "OFFLINE"}]
    if stale_sources:
        score -= min(0.08, len(stale_sources) * 0.02)
        negatives.append(f"source issues: {', '.join(stale_sources[:3])}")

    sample_size = int(_f(order_summary.get("reconciled"), 0) + _f(order_summary.get("total"), 0))
    quality = _sample_quality(sample_size)
    if quality == "WEAK":
        negatives.append("probability estimate has weak sample size")

    probability = max(0.05, min(0.92, score))
    return {
        "estimated_green_probability": round(probability, 3),
        "estimated_green_probability_pct": round(probability * 100.0, 1),
        "confidence_quality": quality,
        "positive_drivers": positives[:5],
        "negative_drivers": negatives[:5],
        "sample_size": sample_size,
        "calibration_warning": "not enough data" if quality == "WEAK" else "",
    }
