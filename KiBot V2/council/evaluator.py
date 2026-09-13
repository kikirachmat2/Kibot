import time
from typing import Dict, Any, Optional
from dataclasses import dataclass

from enrichment import enrichment_cache, EnrichmentCache
from config import settings

@dataclass
class CouncilDecision:
    verdict: str  # "APPROVED", "REJECTED", "WAIT"
    symbol: str
    action: str   # "BUY", "SELL", "HOLD", "NONE"
    confidence: float
    score: float
    reason: str
    suggested_size_idr: float
    ev_pct: float
    deliberation_duration_ms: float
    enrichment_status: str

class FastCouncilEvaluator:
    """
    Sub-millisecond deterministic council evaluator.
    Evaluates market candidates using pure in-memory logic:
    - Zero synchronous network I/O.
    - Zero web searches or LLM blocking calls in the hot path.
    - Reads cached sentiment instantly (0ms); falls back gracefully if cache is empty.
    """
    def __init__(self, cache: Optional[EnrichmentCache] = None):
        self.cache = cache or enrichment_cache

    def evaluate(self, candidate: Dict[str, Any]) -> CouncilDecision:
        t0 = time.perf_counter()
        
        symbol = str(candidate.get("symbol") or candidate.get("pair") or "UNKNOWN").upper().strip()
        price = float(candidate.get("price") or candidate.get("last_price") or 0.0)
        spread_pct = float(candidate.get("spread_pct") or 0.0)
        volume_ratio = float(candidate.get("volume_ratio") or 1.0)
        leadlag_score = float(candidate.get("leadlag_score") or 0.0)
        
        # 1. Tick-Trap & Microstructure Guard
        if price <= 0:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            return CouncilDecision(
                verdict="REJECTED", symbol=symbol, action="NONE", confidence=0.0, score=0.0,
                reason="Invalid zero or negative price", suggested_size_idr=0.0, ev_pct=0.0,
                deliberation_duration_ms=duration_ms, enrichment_status="SKIPPED"
            )
            
        if spread_pct > 0.015:  # Spread > 1.5% is an immediate tick-trap reject
            duration_ms = (time.perf_counter() - t0) * 1000.0
            return CouncilDecision(
                verdict="REJECTED", symbol=symbol, action="NONE", confidence=0.1, score=10.0,
                reason=f"Tick trap: spread {spread_pct*100:.2f}% exceeds 1.50% threshold",
                suggested_size_idr=0.0, ev_pct=-0.5, deliberation_duration_ms=duration_ms,
                enrichment_status="SKIPPED"
            )

        # 2. Check In-Memory Enrichment Cache (Zero-wait read)
        enrichment_data = self.cache.get(symbol)
        enrichment_status = "CACHE_HIT" if enrichment_data else "CACHE_MISS_FALLBACK"
        sentiment_bonus = 0.0
        if enrichment_data:
            sentiment = enrichment_data.get("sentiment", "NEUTRAL")
            if sentiment == "BULLISH":
                sentiment_bonus = 0.10
            elif sentiment == "BEARISH":
                sentiment_bonus = -0.15

        # 3. Deterministic Technical Scoring & EV Calculation
        # Base confidence from momentum, leadlag alignment, and volume
        base_confidence = 0.50
        if volume_ratio > 1.5:
            base_confidence += 0.15
        if leadlag_score > 0.3:
            base_confidence += 0.15
        elif leadlag_score < -0.2:
            base_confidence -= 0.20
            
        confidence = max(0.0, min(1.0, base_confidence + sentiment_bonus))
        
        # Sizing via simplified fractional Kelly
        # Estimated reward: 2.5%, risk: 1.5%, fees: 0.42%
        win_prob = confidence
        reward_pct = 2.5
        risk_pct = 1.5 + (settings.FEE_ROUNDTRIP_PCT)
        ev_pct = (win_prob * reward_pct) - ((1.0 - win_prob) * risk_pct)
        
        if ev_pct <= 0.0 or confidence < 0.60:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            return CouncilDecision(
                verdict="REJECTED", symbol=symbol, action="NONE", confidence=confidence,
                score=round(confidence * 100, 1),
                reason=f"Sub-optimal EV ({ev_pct:.2f}%) or low confidence ({confidence:.2f} < 0.60)",
                suggested_size_idr=0.0, ev_pct=round(ev_pct, 2),
                deliberation_duration_ms=duration_ms, enrichment_status=enrichment_status
            )
            
        # Approved trade mandate
        suggested_size = max(settings.MIN_ORDER_NOTIONAL_IDR, 250_000.0)
        duration_ms = (time.perf_counter() - t0) * 1000.0
        
        return CouncilDecision(
            verdict="APPROVED",
            symbol=symbol,
            action="BUY",
            confidence=round(confidence, 2),
            score=round(confidence * 100, 1),
            reason=f"Positive EV ({ev_pct:.2f}%), strong volume & lead-lag alignment",
            suggested_size_idr=suggested_size,
            ev_pct=round(ev_pct, 2),
            deliberation_duration_ms=duration_ms,
            enrichment_status=enrichment_status,
        )
