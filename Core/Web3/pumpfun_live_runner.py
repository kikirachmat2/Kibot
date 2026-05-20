from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from Core.Exchange.phantom_router import PhantomRouter
from Core.Intelligence.strategy.solana_momentum_meme_strategy import SolanaMomentumMemeStrategy
from Core.Trading.autonomous_sizing import AutonomousSizing
from Core.Web3.pumpfun_fast_scanner import PumpfunFastScanner
from Core.Web3.pumpfun_latency import write_latency
from Core.Web3.pumpfun_native_executor import PumpfunNativeExecutor
from Core.Web3.pumpfun_position_manager import PumpfunPositionManager
from Core.Web3.pumpfun_route_detector import PumpfunRouteDetector
from Core.Web3.web3_quote_router import Web3QuoteRouter
from Core.Web3.web3_safety_checker import Web3SafetyChecker

logger = logging.getLogger("PumpfunLiveRunner")

ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = ROOT / "state"
TREASURY_FILE = STATE_DIR / "phantom_treasury.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _capital_governor_block() -> Dict[str, Any]:
    gov = _read_json(STATE_DIR / "capital_governor.json", {})
    if not isinstance(gov, dict):
        return {"blocked": True, "reason": "capital_governor_missing"}
    allow = bool(gov.get("allow_new_orders", False))
    status = str(gov.get("status") or "").upper()
    reason = str(gov.get("allow_new_orders_reason") or "").strip()
    if allow and status in {"RECONCILED", "RECONCILING"}:
        return {"blocked": False, "reason": "", "state": gov}
    if not reason:
        if status == "BLOCKED_WITH_REASON":
            reason = "capital_governor_global_hard_stop"
        elif status:
            reason = f"capital_governor_status_{status.lower()}"
        else:
            reason = "capital_governor_orders_blocked"
    return {"blocked": True, "reason": reason, "state": gov}


class PumpfunLiveRunner:
    def __init__(self) -> None:
        self.scanner = PumpfunFastScanner()
        self.detector = PumpfunRouteDetector()
        self.strategy = SolanaMomentumMemeStrategy()
        self.safety = Web3SafetyChecker()
        self.router = Web3QuoteRouter()
        self.position_manager = PumpfunPositionManager()
        self.native_executor = PumpfunNativeExecutor()
        self.phantom = PhantomRouter()
        self.sizing = AutonomousSizing()
        self.poll_seconds = float(os.getenv("PUMPFUN_POLL_SECONDS", "5") or 5)
        self.decision_engine = os.getenv("PUMPFUN_DECISION_ENGINE", "SCRIPT_ONLY")
        self.state_file = STATE_DIR / "pumpfun_candidates.json"

    def _load_treasury(self) -> Dict[str, Any]:
        treasury = _read_json(TREASURY_FILE, {})
        return treasury if isinstance(treasury, dict) else {}

    def _write_ai_heartbeat(self, *, best_action: str, venue: str, reason: str, confidence: float, risk_status: str, next_check_seconds: int, market_summary: str) -> None:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "objective": "maximize_risk_adjusted_profit_for_boss",
            "market_summary": market_summary,
            "best_action": best_action,
            "venue": venue,
            "reason": reason,
            "confidence": float(confidence),
            "risk_status": risk_status,
            "next_check_seconds": int(next_check_seconds),
            "mode": "controlled-live",
            "pumpfun_hot_path": "script_only",
            "ai_role": "monitoring_context_summary",
        }
        (STATE_DIR / "ai_decision_trace.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    async def _maybe_trade(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        governor_block = _capital_governor_block()
        if governor_block.get("blocked"):
            return {"status": "BLOCKED_WITH_REASON", "reason": str(governor_block.get("reason") or "capital_governor_orders_blocked")}
        route_type = str(candidate.get("route_type") or "UNSUPPORTED")
        if route_type == "UNSUPPORTED":
            return {"status": "BLOCKED_WITH_REASON", "reason": "unsupported_route"}
        treasury = self._load_treasury()
        trade_size_idr = float(candidate.get("max_trade_idr", 0) or 0.0)
        if trade_size_idr <= 0:
            trade_size_idr = float(candidate.get("sizing", {}).get("size_idr", 0) or 0.0)

        sizing = self.sizing.size(
            total_capital_idr=0.0,
            venue_capital_idr=0.0,
            route_bucket_idr=0.0,
            available_balance_idr=0.0,
            daily_risk_remaining_idr=0.0,
            liquidity_usd=float(candidate.get("liquidity_usd", 0) or 0),
            slippage_pct=float(candidate.get("slippage_pct", 0) or 0),
            confidence=float(candidate.get("safety_score", 0) or 0) / 100.0,
            ev_pct=float(candidate.get("ev_pct", 0) or 0),
            volatility_pct=float(candidate.get("momentum_score", 0) or 0),
            current_open_exposure_idr=0.0,
            exit_available=bool(candidate.get("can_sell")),
            route="pumpfun",
            reserve_locked=True,
            hard_cap_idr=float(candidate.get("max_trade_idr", 0) or 0),
            liquidity_safe_size_idr=float(candidate.get("max_trade_idr", 0) or 0),
            momentum_score=float(candidate.get("momentum_score", 0) or 0),
            exit_quality=str(candidate.get("route_state", {}).get("reason") or ""),
            trade_grade=str(candidate.get("decision") or ""),
            stop_loss_pct=float(candidate.get("stop_loss_pct", 3) or 3),
            route_min_trade_idr=float(candidate.get("max_trade_idr", 0) or 0),
        )
        candidate["sizing"] = sizing

        if not candidate.get("can_sell", False):
            return {"status": "BLOCKED_WITH_REASON", "reason": "no_sell_route"}

        if route_type == "PUMPFUN_BONDING_CURVE":
            native_status = self.native_executor.get_status()
            return {"status": native_status.get("status", "BLOCKED_WITH_REASON"), "reason": native_status.get("reason", "")}

        if route_type == "JUPITER_ROUTABLE":
            quote = candidate.get("route_state", {}).get("jupiter_quote") or {}
            if not quote.get("quote_ok"):
                quote = await self.router.quote(
                    route="solana",
                    input_asset="So11111111111111111111111111111111111111112",
                    output_asset=str(candidate.get("mint") or ""),
                    amount_raw=int(candidate.get("max_trade_idr", 0) or 0),
                    trade_size_idr=trade_size_idr,
                    balance_snapshot=treasury,
                    route_context={"source": "pumpfun_live_runner", "mint": candidate.get("mint"), "route_type": route_type},
                )
            if not quote.get("quote_ok"):
                return {"status": "BLOCKED_WITH_REASON", "reason": "no_buy_route"}
            fee_state = quote.get("fee_intelligence") or candidate.get("fee_intelligence") or {}
            if isinstance(fee_state, dict) and not bool(fee_state.get("gas_affordable", True)):
                return {
                    "status": "BLOCKED_WITH_REASON",
                    "reason": str(fee_state.get("gas_reason") or "gas_fee_unaffordable"),
                    "fee_intelligence": fee_state,
                }
            return {"status": "READY", "reason": "jupiter_routable"}

        return {"status": "BLOCKED_WITH_REASON", "reason": "native_executor_not_ready"}

    async def tick(self) -> Dict[str, Any]:
        start = time.perf_counter()
        scan_start = time.perf_counter()
        state = await self.scanner.scan()
        scan_ms = int((time.perf_counter() - scan_start) * 1000)

        best = state.get("best_candidate") if isinstance(state, dict) else {}
        route_ms = 0
        sizing_ms = 0
        build_ms = 0
        submit_ms = 0
        confirm_ms = 0
        action = "WAIT"
        reason = "no_candidate"

        if best:
            action = "SCAN"
            route_start = time.perf_counter()
            treasury = self._load_treasury()
            route_state = await self.detector.detect_best_effort(
                best.get("mint", ""),
                pair_hint=best.get("pair") if isinstance(best.get("pair"), dict) else {},
                trade_size_idr=float(best.get("max_trade_idr", 0) or 0.0),
                balance_snapshot=treasury,
            )
            route_ms = int((time.perf_counter() - route_start) * 1000)
            best["route_state"] = route_state
            best["route_type"] = route_state.get("route_type")
            best["can_buy"] = bool(route_state.get("buy_route_available"))
            best["can_sell"] = bool(route_state.get("sell_route_available"))

            score = self.strategy.evaluate_candidate(best)
            best.update(score)
            size_start = time.perf_counter()
            sizing = self.sizing.size(
                route="pumpfun",
                total_capital_idr=0.0,
                venue_capital_idr=0.0,
                route_bucket_idr=float(best.get("max_trade_idr", 0) or 0.0),
                available_balance_idr=float(best.get("max_trade_idr", 0) or 0.0),
                daily_risk_remaining_idr=float(best.get("max_trade_idr", 0) or 0.0),
                liquidity_usd=float(best.get("liquidity_usd", 0) or 0),
                slippage_pct=float(best.get("slippage_pct", 0) or 0),
                confidence=float(best.get("safety_score", 0) or 0) / 100.0,
                ev_pct=float(best.get("ev_pct", 0) or 0),
                volatility_pct=float(best.get("momentum_score", 0) or 0),
                current_open_exposure_idr=0.0,
                exit_available=bool(best.get("can_sell")),
                reserve_locked=True,
                hard_cap_idr=float(best.get("max_trade_idr", 0) or 0),
                liquidity_safe_size_idr=float(best.get("max_trade_idr", 0) or 0),
                momentum_score=float(best.get("momentum_score", 0) or 0),
                exit_quality=str(best.get("route_state", {}).get("reason") or ""),
                trade_grade=str(best.get("decision") or ""),
                stop_loss_pct=float(best.get("stop_loss_pct", 3) or 3),
                route_min_trade_idr=float(best.get("max_trade_idr", 0) or 0),
            )
            sizing_ms = int((time.perf_counter() - size_start) * 1000)
            best["sizing"] = sizing
            reason = best.get("reason") or "scanned"

            # hot path is intentionally deterministic and conservative:
            candidate_action = await self._maybe_trade(best)
            action = candidate_action.get("status", action)
            reason = candidate_action.get("reason", reason)

        latency = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_scan_ms": scan_ms,
            "last_route_detect_ms": route_ms,
            "last_sizing_ms": sizing_ms,
            "last_build_tx_ms": build_ms,
            "last_submit_ms": submit_ms,
            "last_confirm_ms": confirm_ms,
            "hot_path_total_ms": int((time.perf_counter() - start) * 1000),
            "decision_source": "script_only",
        }
        write_latency(latency)

        try:
            self._write_ai_heartbeat(
                best_action="SCAN" if best else "WAIT",
                venue="pumpfun",
                reason=reason,
                confidence=float((best or {}).get("safety_score", 0) or 0) / 100.0,
                risk_status="READY" if (best and best.get("can_sell")) else "BLOCKED",
                next_check_seconds=max(1, int(self.poll_seconds)),
                market_summary=str((best or {}).get("symbol") or (best or {}).get("mint") or "pumpfun live runner heartbeat"),
            )
        except Exception as exc:
            logger.warning("Pumpfun AI heartbeat write failed: %s", exc)

        state.update(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "runner": "ACTIVE",
                "scan_interval_ms": int(self.poll_seconds * 1000),
                "candidates_found": int(len(state.get("candidates", []) or [])),
                "hot_queue": list((state.get("candidates", []) or [])[:5]),
                "best_candidate": best or {},
                "approved_candidates": list((state.get("candidates", []) or [])[:3]),
                "rejected": state.get("rejected", []),
                "current_action": action,
                "reason": reason,
                "latency": latency,
                "decision_engine": self.decision_engine,
                "ai_role": "monitoring_context_summary",
            }
        )
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        return state

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                logger.exception("Pumpfun runner tick failed: %s", exc)
            await asyncio.sleep(self.poll_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(PumpfunLiveRunner().run_forever())


if __name__ == "__main__":
    main()
