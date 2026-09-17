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
    kelly_fraction: float
    rr_ratio: float
    deliberation_duration_ms: float
    enrichment_status: str
    target_tp_pct: float = 1.8
    target_sl_pct: float = 2.4
    strategy: str = "NONE"
    max_hold_time_s: int = 0
    atr14: float = 0.0

class FastCouncilEvaluator:
    """
    Sub-millisecond deterministic council evaluator.
    Port of canonical V1 mathematical gating (expected_value.py):
    - Net-of-fee Expected Value: EV = (p * avg_win_net) - (q * avg_loss_net) >= 0.3%
    - Reward-to-Risk ratio: RR = avg_win_net / avg_loss_net >= 1.40
    - Half-Kelly criterion: f* = 0.5 * ((b*p - q) / b) >= 0.01 (capped at 25%)
    - Microstructure tick-trap guard: spread < 1.50%
    - Semi-dynamic TP/SL modeling based on candidate momentum and microstructure
    - Zero synchronous network I/O, zero hot-path LLM calls.
    """
    def __init__(self, cache: Optional[EnrichmentCache] = None):
        self.cache = cache or enrichment_cache

    def evaluate(self, candidate: Dict[str, Any], bankroll_idr: float = 10_000_000.0) -> CouncilDecision:
        t0 = time.perf_counter()
        
        symbol = str(candidate.get("symbol") or candidate.get("pair") or "UNKNOWN").upper().strip()
        price = float(candidate.get("price") or candidate.get("last_price") or 0.0)
        spread_pct = float(candidate.get("spread_pct") or 0.0)
        volume_ratio = float(candidate.get("volume_ratio") or 1.0)
        leadlag_score = float(candidate.get("leadlag_score") or 0.0)
        
        # 1. Tick-Trap & Microstructure Guard (SignalQuality port)
        if price <= 0:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            return CouncilDecision(
                verdict="REJECTED", symbol=symbol, action="NONE", confidence=0.0, score=0.0,
                reason="Invalid zero or negative price", suggested_size_idr=0.0, ev_pct=0.0,
                kelly_fraction=0.0, rr_ratio=0.0, deliberation_duration_ms=duration_ms, enrichment_status="SKIPPED"
            )
            
        if spread_pct > 0.015:  # Spread > 1.5% is an immediate tick-trap reject
            duration_ms = (time.perf_counter() - t0) * 1000.0
            return CouncilDecision(
                verdict="REJECTED", symbol=symbol, action="NONE", confidence=0.1, score=10.0,
                reason=f"Tick trap: spread {spread_pct*100:.2f}% exceeds 1.50% threshold",
                suggested_size_idr=0.0, ev_pct=-0.5, kelly_fraction=0.0, rr_ratio=0.0,
                deliberation_duration_ms=duration_ms, enrichment_status="SKIPPED"
            )

        # 2. Check In-Memory Enrichment Cache (Zero-wait read)
        enrichment_data = self.cache.get(symbol)
        enrichment_status = "CACHE_HIT" if enrichment_data else "CACHE_MISS_FALLBACK"
        sentiment_bonus = 0.0
        if enrichment_data:
            sentiment = enrichment_data.get("sentiment", "NEUTRAL")
            if sentiment == "BULLISH":
                sentiment_bonus = 0.08
            elif sentiment == "BEARISH":
                sentiment_bonus = -0.12

        # 3. Probability Estimation (Win Probability p)
        # Calibrated to V1 APPROVED empirical realized win rate (36.7%)
        base_p = 0.35
        if volume_ratio >= 1.5:
            base_p += 0.10
        if leadlag_score > 0.3:
            base_p += 0.08
        elif leadlag_score < -0.2:
            base_p -= 0.15
            
        win_prob = max(0.10, min(0.90, base_p + sentiment_bonus))
        loss_prob = 1.0 - win_prob

        # 4. Canonical Expected Value & Kelly Math with Semi-Dynamic TP/SL Targets
        # Resolves structural gate lockout by modeling candidate-specific asymmetric potential
        if "avg_win_pct" in candidate:
            avg_win_gross = float(candidate["avg_win_pct"])
        else:
            # Semi-dynamic TP: expands upside on strong leadlag, volume surge, and high 24h volatility
            tp_bonus = 0.0
            if leadlag_score > 0.0:
                tp_bonus += leadlag_score * 0.018  # Strong leadlag expands breakout target
            if volume_ratio > 1.0:
                tp_bonus += min(0.015, (volume_ratio - 1.0) * 0.010)
            if sentiment_bonus > 0:
                tp_bonus += 0.005
            high_24h = float(candidate.get("high_24h") or price)
            low_24h = float(candidate.get("low_24h") or price)
            if price > 0 and high_24h > low_24h:
                range_pct = (high_24h - low_24h) / price
                if range_pct > 0.05:
                    tp_bonus += min(0.01, (range_pct - 0.05) * 0.15)
            avg_win_gross = max(0.018, 0.028 + tp_bonus)

        if "avg_loss_pct" in candidate:
            avg_loss_gross = float(candidate["avg_loss_pct"])
        else:
            # Semi-dynamic SL: tighter for liquid/tight-spread pairs, wider buffer for wider spreads
            avg_loss_gross = max(0.018, 0.020 + (spread_pct * 1.5))

        fee_pct = settings.FEE_ROUNDTRIP_PCT / 100.0  # e.g. 0.0042 (0.42%)
        slippage_pct = 0.001                         # 0.1%

        avg_win_net = max(0.0, avg_win_gross - fee_pct - slippage_pct)
        avg_loss_net = max(0.0001, avg_loss_gross + fee_pct + slippage_pct)

        ev = (win_prob * avg_win_net) - (loss_prob * avg_loss_net)
        rr_ratio = avg_win_net / avg_loss_net if avg_loss_net > 0 else 0.0

        # Kelly Criterion: f* = (b*p - q) / b
        b = avg_win_net / avg_loss_net if avg_loss_net > 0 else 0.0
        kelly_raw = ((b * win_prob) - loss_prob) / b if b > 0 else 0.0
        kelly = max(0.0, min(0.25, kelly_raw * 0.5))  # Half-Kelly capped at 25% max

        # 5. Canonical Gating Thresholds
        rejection_reasons = []
        if ev < 0.003:  # EV < 0.3%
            rejection_reasons.append(f"EV {ev*100:.2f}% below threshold 0.30%")
        if rr_ratio < 1.4:  # R:R buffer
            rejection_reasons.append(f"R:R {rr_ratio:.2f} below minimum 1.40")
        if kelly < 0.01:  # Kelly floor 1%
            rejection_reasons.append(f"Kelly {kelly:.4f} below floor 0.0100")
        if win_prob < 0.45:
            rejection_reasons.append(f"Win probability {win_prob*100:.1f}% below 45.0%")

        duration_ms = (time.perf_counter() - t0) * 1000.0

        if rejection_reasons:
            return CouncilDecision(
                verdict="REJECTED",
                symbol=symbol,
                action="NONE",
                confidence=round(win_prob, 2),
                score=round(win_prob * 100, 1),
                reason="; ".join(rejection_reasons),
                suggested_size_idr=0.0,
                ev_pct=round(ev * 100, 3),
                kelly_fraction=round(kelly, 4),
                rr_ratio=round(rr_ratio, 2),
                deliberation_duration_ms=duration_ms,
                enrichment_status=enrichment_status,
                target_tp_pct=round(avg_win_gross * 100, 2),
                target_sl_pct=round(avg_loss_gross * 100, 2),
            )

        # Dynamic position sizing based on Kelly fraction
        suggested_size = max(settings.MIN_ORDER_NOTIONAL_IDR, min(bankroll_idr * 0.15, bankroll_idr * kelly))

        return CouncilDecision(
            verdict="APPROVED",
            symbol=symbol,
            action="BUY",
            confidence=round(win_prob, 2),
            score=round(win_prob * 100, 1),
            reason=f"Canonical EV approved ({ev*100:.2f}% >= 0.3%), R:R {rr_ratio:.2f}, Kelly {kelly:.3f} (TP: {avg_win_gross*100:.2f}%, SL: {avg_loss_gross*100:.2f}%)",
            suggested_size_idr=suggested_size,
            ev_pct=round(ev * 100, 3),
            kelly_fraction=round(kelly, 4),
            rr_ratio=round(rr_ratio, 2),
            deliberation_duration_ms=duration_ms,
            enrichment_status=enrichment_status,
            target_tp_pct=round(avg_win_gross * 100, 2),
            target_sl_pct=round(avg_loss_gross * 100, 2),
        )
