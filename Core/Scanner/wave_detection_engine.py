import logging
from typing import Any, Dict

logger = logging.getLogger("WaveDetectionEngine")

class WaveDetectionEngine:
    """
    Deterministic metric-driven classification engine for market-wide wave scoring.
    Evaluates momentum, liquidity expansion, exits, and risks to determine wave phase.
    """

    def evaluate_token(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        symbol = str(token_data.get("symbol") or "UNK").upper()
        mint = str(token_data.get("mint") or "")
        chain = str(token_data.get("chain") or "solana").lower()
        sector = str(token_data.get("sector") or "solana_meme").lower()

        # Extract metric parameters safely
        price_accel = float(token_data.get("price_acceleration", 0.0) or 0.0)
        vol_accel = float(token_data.get("volume_acceleration", 0.0) or 0.0)
        imbalance = float(token_data.get("buy_sell_imbalance", 0.5) or 0.5) # 0.5 means balanced
        liq_expansion = float(token_data.get("liquidity_expansion", 0.0) or 0.0)
        curve_progress = float(token_data.get("bonding_curve_progress", 0.0) or 0.0)
        holder_growth = float(token_data.get("holder_growth_pct", 0.0) or 0.0)
        fresh_pair = bool(token_data.get("fresh_pair_creation", False))
        migrated = bool(token_data.get("migration_event", False))
        has_route = bool(token_data.get("route_availability", True))
        mc_expansion = float(token_data.get("market_cap_expansion", 0.0) or 0.0)
        green_candles = int(token_data.get("repeated_green_candles", 0) or 0)
        pullback = bool(token_data.get("pullback_after_pump", False))
        exit_quality = float(token_data.get("exit_liquidity_quality", 0.8) or 0.8)

        # Core quantitative score components
        momentum_score = min(100.0, max(0.0, (price_accel * 4.0) + (vol_accel * 3.0) + (green_candles * 5.0)))
        liquidity_score = min(100.0, max(0.0, (liq_expansion * 5.0) + (holder_growth * 2.0)))
        exit_score = min(100.0, max(0.0, exit_quality * 100.0))
        risk_score = 0.0

        if not has_route:
            risk_score += 50.0
        if imbalance < 0.2: # Heavy dumping
            risk_score += 40.0
        if mc_expansion > 500.0: # Extreme parabolic risk
            risk_score += 20.0

        # Classify wave phase deterministic criteria
        if migrated:
            wave_phase = "MIGRATED"
        elif fresh_pair and curve_progress == 0:
            wave_phase = "NEW_LAUNCH"
        elif price_accel > 15.0 and vol_accel > 10.0 and mc_expansion < 100.0:
            wave_phase = "EARLY_PUMP"
        elif price_accel > 30.0 and green_candles >= 5:
            wave_phase = "MID_PUMP"
        elif mc_expansion > 300.0 and price_accel < 5.0:
            wave_phase = "LATE_PUMP"
        elif imbalance < 0.15 or price_accel < -20.0:
            wave_phase = "DUMPING"
        elif imbalance < 0.35:
            wave_phase = "EXHAUSTED"
        else:
            wave_phase = "EARLY_PUMP" # Default early detection bias

        if risk_score > 60.0 or wave_phase in ["DUMPING", "EXHAUSTED"]:
            wave_phase = "UNSAFE"

        # Calculate final wave score
        wave_score = min(100.0, max(0.0, (momentum_score * 0.4) + (liquidity_score * 0.3) + (exit_score * 0.3) - (risk_score * 0.2)))

        # Determine decision & reason
        decision = "WATCH"
        reason = "Scanning for acceleration metrics."

        if wave_phase in ["DUMPING", "EXHAUSTED", "UNSAFE"]:
            decision = "REJECT"
            reason = f"Unsafe risk indicators (score: {risk_score:.1f})."
        elif not has_route:
            decision = "REJECT"
            reason = "No exit route available."
        elif wave_score > 65.0 and wave_phase in ["EARLY_PUMP", "NEW_LAUNCH", "MIGRATED"]:
            decision = "APPROVE"
            reason = f"Strong momentum wave in phase {wave_phase}."
        elif wave_score > 40.0:
            decision = "WATCH"
            reason = f"Moderately active wave ({wave_phase})."

        return {
            "symbol": symbol,
            "mint": mint,
            "chain": chain,
            "sector": sector,
            "wave_phase": wave_phase,
            "wave_score": round(wave_score, 1),
            "momentum_score": round(momentum_score, 1),
            "liquidity_score": round(liquidity_score, 1),
            "exit_score": round(exit_score, 1),
            "risk_score": round(risk_score, 1),
            "route_status": "AVAILABLE" if has_route else "UNAVAILABLE",
            "decision": decision,
            "reason": reason
        }
