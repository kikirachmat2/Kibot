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
        return max(0.0, min(0.35, base))

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
    ) -> Dict[str, Any]:
        hard_reasons = []
        if not exit_available:
            hard_reasons.append("exit_unavailable")
        if daily_risk_remaining_idr <= 0:
            hard_reasons.append("daily_risk_exhausted")
        if available_balance_idr <= 0:
            hard_reasons.append("no_available_balance")

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
            }
            self._save(payload)
            return payload

        fraction = self._score_fraction(
            confidence=confidence,
            ev_pct=ev_pct,
            liquidity_usd=liquidity_usd,
            slippage_pct=slippage_pct,
            daily_risk_remaining_idr=daily_risk_remaining_idr,
            route_bucket_idr=route_bucket_idr,
            exposure_idr=current_open_exposure_idr,
            volatility_pct=volatility_pct,
        )

        if reserve_locked and route_bucket_idr > 0:
            route_budget = route_bucket_idr
        else:
            route_budget = min(route_bucket_idr or available_balance_idr, available_balance_idr)

        size_idr = min(
            available_balance_idr * 0.98,
            daily_risk_remaining_idr * 0.50,
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
        if size_idr < self.min_trade_idr:
            approved = False
            reason = "below_min_trade"
        else:
            approved = True
            reason = "approved"

        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "route": route,
            "approved": approved,
            "size_idr": round(size_idr, 2),
            "capital_fraction": round(float(size_idr / max(total_capital_idr, 1.0)), 4),
            "confidence": round(float(confidence or 0), 3),
            "reason": reason,
            "max_loss_if_stop_hit_idr": round(size_idr * max(0.0, float(os.getenv("AUTONOMOUS_SIZE_STOP_LOSS_PCT", "3") or 3)) / 100.0, 2),
        }
        self._save(payload)
        return payload

