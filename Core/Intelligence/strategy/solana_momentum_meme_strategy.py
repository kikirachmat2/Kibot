import os
from typing import Any, Dict


class SolanaMomentumMemeStrategy:
    """Score Solana meme candidates for controlled-live execution."""

    def __init__(self) -> None:
        self.min_liquidity_usd = float(os.getenv("WEB3_MEME_MIN_LIQUIDITY_USD", "10000") or 10000)
        self.min_volume_1h_usd = float(os.getenv("WEB3_MEME_MIN_VOLUME_1H_USD", "5000") or 5000)
        self.max_price_impact_pct = float(os.getenv("WEB3_MEME_MAX_PRICE_IMPACT_PCT", "2.5") or 2.5)
        self.min_safety_score = float(os.getenv("WEB3_MEME_MIN_SAFETY_SCORE", "65") or 65)
        self.max_trade_idr = float(os.getenv("WEB3_MEME_MAX_TRADE_IDR", "5000") or 5000)
        self.stop_loss_pct = float(os.getenv("WEB3_MEME_STOP_LOSS_PCT", "3") or 3)
        self.take_profit_pct = float(os.getenv("WEB3_MEME_TAKE_PROFIT_PCT", "7") or 7)
        self.trailing_stop_pct = float(os.getenv("WEB3_MEME_TRAILING_STOP_PCT", "2") or 2)
        self.time_stop_seconds = int(float(os.getenv("WEB3_MEME_TIME_STOP_SECONDS", "1200") or 1200))

    def _momentum_score(self, c: Dict[str, Any]) -> float:
        ch5 = float(c.get("change_5m_pct", 0) or 0)
        ch1 = float(c.get("change_1h_pct", 0) or 0)
        ch24 = float(c.get("change_24h_pct", 0) or 0)
        vol1h = float(c.get("volume_1h_usd", 0) or 0)
        vol5m = float(c.get("volume_5m_usd", 0) or 0)
        age = float(c.get("age_minutes", 0) or 0)
        score = max(0.0, ch5 * 1.8 + ch1 * 1.1 + min(ch24, 250.0) * 0.15)
        if vol1h > 0:
            score += min(25.0, vol1h / 2500.0)
        if vol5m > 0:
            score += min(10.0, vol5m / 1500.0)
        if age < 30:
            score += 10.0
        elif age > 480:
            score -= 8.0
        if ch5 < 0 and ch1 < 0:
            score -= 15.0
        if ch24 > 300 and ch5 < 2:
            score -= 12.0
        return max(0.0, min(100.0, score))

    def evaluate_candidate(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        liquidity = float(candidate.get("liquidity_usd", 0) or 0)
        vol_1h = float(candidate.get("volume_1h_usd", 0) or 0)
        price_impact = float(candidate.get("price_impact_pct", candidate.get("slippage_pct", 0)) or 0)
        change_24h = float(candidate.get("change_24h_pct", 0) or 0)
        safety_score = float(candidate.get("safety_score", 0) or 0)
        holders = int(candidate.get("holders", 0) or 0)
        age = float(candidate.get("age_minutes", 0) or 0)
        route_type = str(candidate.get("route_type") or "").upper()
        route_state = candidate.get("route_state") if isinstance(candidate.get("route_state"), dict) else {}

        reasons = []
        if liquidity < self.min_liquidity_usd:
            reasons.append("liquidity_too_thin")
        if vol_1h < self.min_volume_1h_usd:
            reasons.append("volume_too_low")
        if price_impact > self.max_price_impact_pct:
            reasons.append("price_impact_too_high")
        if safety_score and safety_score < self.min_safety_score:
            reasons.append("safety_score_low")
        if change_24h > 500 and vol_1h < self.min_volume_1h_usd * 2:
            reasons.append("already_too_pumped")
        if age and age < 2:
            reasons.append("token_too_new")
        if holders and holders < 10:
            reasons.append("holder_base_too_small")

        momentum_score = self._momentum_score(candidate)
        if safety_score <= 0:
            safety_score = 0.0
        if route_type == "PUMPFUN_BONDING_CURVE" and not bool(route_state.get("sell_route_available", False)):
            reasons.append("no_exit_route")
        if route_type == "UNSUPPORTED":
            reasons.append("unsupported_route")

        ev_pct = round((momentum_score * 0.12) + (safety_score * 0.08) - (price_impact * 4.0), 2)
        decision = "APPROVE" if not reasons and momentum_score >= 35 and ev_pct > 0 else "REJECT"
        reason = "ok" if decision == "APPROVE" else ";".join(reasons) if reasons else "ev_non_positive"

        liquidity_safe_size = max(0.0, liquidity * 0.015)
        safe_size = min(
            self.max_trade_idr,
            liquidity_safe_size * 16000.0 if liquidity_safe_size else self.max_trade_idr,
        )
        safe_size = max(0.0, safe_size)

        return {
            "momentum_score": round(momentum_score, 2),
            "safety_score": round(max(safety_score, 0.0), 2),
            "ev_pct": ev_pct,
            "decision": decision,
            "reason": reason,
            "max_trade_idr": int(safe_size),
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "trailing_stop_pct": self.trailing_stop_pct,
            "time_stop_seconds": self.time_stop_seconds,
            "exit_plan_required": True,
        }
