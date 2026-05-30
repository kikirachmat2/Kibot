import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
SIZING_FILE = STATE_DIR / "autonomous_sizing.json"


class AutonomousSizing:
    """Deterministic live sizing engine for controlled-live KiBot."""

    def __init__(self) -> None:
        self.mode = os.getenv("KIBOT_SIZING_MODE", "AUTONOMOUS").upper()
        self.allow_hardcoded_caps = os.getenv("KIBOT_HARDCODED_TRADE_CAP_DISABLED", "true").lower() != "true"
        self.capital_governor_decides = os.getenv("KIBOT_CAPITAL_GOVERNOR_DECIDES_SIZE", "true").lower() == "true"
        self.route_ceiling_idr = float(os.getenv("KIBOT_ROUTE_MAX_TRADE_IDR", "0") or 0)
        self.min_trade_idr = float(os.getenv("KIBOT_MIN_TRADE_IDR", "10000") or 10000)
        self.adaptive_profile = os.getenv("KIBOT_ADAPTIVE_GUARD_PROFILE", "BALANCED_PROBE").upper()
        self.aggressive_probe_enabled = os.getenv("KIBOT_AGGRESSIVE_PROBE_ENABLED", "false").lower() == "true"
        self.probe_min_confidence = float(os.getenv("KIBOT_PROBE_MIN_CONFIDENCE", "0.78") or 0.78)
        self.probe_min_momentum = float(os.getenv("KIBOT_PROBE_MIN_MOMENTUM", "0.70") or 0.70)
        self.probe_risk_fraction = float(os.getenv("KIBOT_PROBE_RISK_FRACTION", "0.03") or 0.03)

    def _save(self, payload: Dict[str, Any]) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        SIZING_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    def _score_fraction(self, *, confidence: float, ev_pct: float, liquidity_usd: float, slippage_pct: float, daily_risk_remaining_idr: float, route_bucket_idr: float, exposure_idr: float, volatility_pct: float) -> float:
        conf = max(0.0, min(1.0, confidence))
        ev = max(0.0, min(1.0, ev_pct / 10.0))
        liq = max(0.0, min(1.0, liquidity_usd / 25000.0))
        slip = max(0.0, min(1.0, 1.0 - (slippage_pct / 5.0)))
        risk = 1.0 if daily_risk_remaining_idr > 0 else 0.0
        bucket = max(0.0, min(1.0, route_bucket_idr / 50000.0 if route_bucket_idr else 0.2))
        exposure_penalty = 1.0 if exposure_idr <= 0 else max(0.2, 1.0 - min(exposure_idr / max(route_bucket_idr, 1.0), 0.8))
        vol = max(0.15, min(1.0, 1.0 - (volatility_pct / 25.0)))
        base = (0.12 + 0.28 * conf + 0.18 * ev + 0.16 * liq + 0.10 * slip + 0.08 * risk + 0.08 * bucket + 0.04 * exposure_penalty + 0.04 * vol)
        return max(0.0, min(0.05, base))

    def size(
        self,
        *,
        total_capital_idr: float,
        venue_capital_idr: float,
        route_bucket_idr: float,
        available_balance_idr: float,
        daily_risk_remaining_idr: float,
        liquidity_usd: float,
        slippage_pct: float,
        confidence: float,
        ev_pct: float,
        volatility_pct: float = 0.0,
        current_open_exposure_idr: float = 0.0,
        exit_available: bool = True,
        route: str = "",
        reserve_locked: bool = True,
        hard_cap_idr: float = 0.0,
        liquidity_safe_size_idr: float = 0.0,
        momentum_score: float = 0.0,
        exit_quality: str = "",
        trade_grade: str = "",
        stop_loss_pct: float = 0.0,
        route_min_trade_idr: float = 0.0,
    ) -> Dict[str, Any]:
        hard_reasons = []
        if not exit_available:
            hard_reasons.append("exit_unavailable")
        if available_balance_idr <= 0:
            hard_reasons.append("no_available_balance")
        recovery_probe = False

        if hard_reasons:
            payload = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "route": route,
                "approved": False,
                "size_idr": 0,
                "capital_fraction": 0,
                "confidence": round(float(confidence or 0), 3),
                "reason": ";".join(hard_reasons),
                "max_loss_if_stop_hit_idr": 0,
                "guard_layer": "HARD_BLOCK",
                "guard_action": "BLOCK_ORDER",
                "probe_mode": False,
                "guard_reasons": hard_reasons,
            }
            self._save(payload)
            return payload

        fraction = self._score_fraction(
            confidence=confidence,
            ev_pct=ev_pct,
            liquidity_usd=liquidity_usd,
            slippage_pct=slippage_pct,
            daily_risk_remaining_idr=max(daily_risk_remaining_idr, 0.0),
            route_bucket_idr=route_bucket_idr,
            exposure_idr=current_open_exposure_idr,
            volatility_pct=volatility_pct,
        )

        if reserve_locked and route_bucket_idr > 0:
            route_budget = route_bucket_idr
        else:
            route_budget = min(route_bucket_idr or available_balance_idr, available_balance_idr)

        effective_min_trade_idr = float(route_min_trade_idr or self.min_trade_idr)
        stop_loss_pct = float(stop_loss_pct or os.getenv("AUTONOMOUS_SIZE_STOP_LOSS_PCT", "3") or 3)
        stop_loss_fraction = max(0.001, stop_loss_pct / 100.0)
        if daily_risk_remaining_idr > 0:
            risk_notional_cap = daily_risk_remaining_idr * 0.90 / stop_loss_fraction
        else:
            risk_notional_cap = 0.0

        quality_reasons = []
        if ev_pct <= 0:
            quality_reasons.append("ev_not_positive")
        if confidence < 0.62:
            quality_reasons.append("confidence_low")
        if liquidity_usd > 0 and liquidity_usd < 5000:
            quality_reasons.append("liquidity_thin")
        if slippage_pct > float(os.getenv("KIBOT_ADAPTIVE_MAX_SLIPPAGE_PCT", "3.0") or 3.0):
            quality_reasons.append("slippage_high")

        exit_grade_ok = str(exit_quality or trade_grade or "").upper() in {"A", "B", "A+", "A-"}
        momentum_ok = max(float(momentum_score or 0.0), min(1.0, max(0.0, volatility_pct) / 25.0)) >= self.probe_min_momentum
        probe_mode = bool(
            self.aggressive_probe_enabled
            and self.adaptive_profile != "CONSERVATIVE"
            and confidence >= self.probe_min_confidence
            and (momentum_ok or exit_grade_ok)
            and ev_pct > 0
            and daily_risk_remaining_idr > 0
        )

        size_idr = min(
            available_balance_idr * 0.98,
            risk_notional_cap,
            total_capital_idr * fraction,
            route_budget * fraction if route_budget > 0 else available_balance_idr * fraction,
        )
        if liquidity_safe_size_idr > 0:
            size_idr = min(size_idr, liquidity_safe_size_idr)
        if hard_cap_idr > 0:
            size_idr = min(size_idr, hard_cap_idr)
        if self.route_ceiling_idr > 0 and not self.allow_hardcoded_caps:
            size_idr = min(size_idr, self.route_ceiling_idr)

        size_idr = max(0.0, size_idr)

        if size_idr < effective_min_trade_idr and probe_mode:
            probe_cap = min(
                available_balance_idr * 0.98,
                route_budget * min(0.35, max(0.05, self.probe_risk_fraction)) if route_budget > 0 else available_balance_idr * 0.10,
                risk_notional_cap,
            )
            if probe_cap >= effective_min_trade_idr:
                size_idr = effective_min_trade_idr

        if ev_pct <= 0:
            approved = False
            reason = "ev_not_positive"
            size_idr = 0.0
        elif size_idr < effective_min_trade_idr:
            approved = False
            reason = "below_min_trade"
        else:
            approved = True
            reason = "aggressive_probe" if probe_mode and quality_reasons else "approved"

        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "route": route,
            "approved": approved,
            "size_idr": round(size_idr, 2),
            "capital_fraction": round(float(size_idr / max(total_capital_idr, 1.0)), 4),
            "confidence": round(float(confidence or 0), 3),
            "reason": reason,
            "max_loss_if_stop_hit_idr": round(size_idr * stop_loss_fraction, 2),
            "risk_notional_cap_idr": round(risk_notional_cap, 2),
            "effective_min_trade_idr": round(effective_min_trade_idr, 2),
            "stop_loss_pct": round(stop_loss_pct, 3),
            "guard_layer": "RECOVERY_GATE" if recovery_probe else ("OPPORTUNITY_GATE" if quality_reasons else "HARD_SAFETY_PASS"),
            "guard_action": "PROBE_APPROVED" if reason in {"aggressive_probe", "recovery_probe"} else ("APPROVE_ORDER" if approved else "REJECT_CANDIDATE_KEEP_SCANNING"),
            "probe_mode": bool(probe_mode),
            "guard_reasons": quality_reasons,
            "scanner_should_continue": not approved,
        }
        self._save(payload)
        return payload
