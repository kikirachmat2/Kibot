from __future__ import annotations
import os, json, time, asyncio, logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from Core.Support.ki_vault import load_sovereign_env
from Core.Intelligence.kibot_ai_coordinator import query_ai
from Core.Intelligence.kibot_ai_search import AISearchService
from Core.sovereign_state import save_strategy, load_strategy, set_urgency, load_pnl_history
from Core.Intelligence.daily_context import get_daily_context
from Core.Intelligence.market_heatmap import load_heatmap
from Core.Intelligence.probability_engine import estimate_green_probability
from Core.Intelligence.decision_journal import log_council_decision
from Core.Intelligence.exit_plan import build_exit_plan

logger = logging.getLogger("SovereignCouncil")

WIB_UTC_OFFSET_HOURS = int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7"))
WIB_TZ = timezone(timedelta(hours=WIB_UTC_OFFSET_HOURS))

class SovereignCouncil:
    """
    Sovereign Council of KiBot
    The supreme deliberation engine for both system integrity and trading directives.
    Uses the centralized AI Coordinator for robust, multi-provider intelligence.
    """
    def __init__(self):
        base_dir = Path(__file__).resolve().parent.parent
        self.state_dir = base_dir / "state"
        self.decision_log = self.state_dir / "council_decisions.jsonl"
        self.directive_log = self.state_dir / "council_directives.json"
        self.whatif_file = self.state_dir / "whatif_results.json"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # Ensure vital autonomy state files exist with default secure skeletons (Phase 6)
        autonomy_defaults = {
            "expected_value.json": {"schema_version": 1, "status": "idle", "strategies": {}},
            "signal_quality.json": [],
            "strategy_scorecard.json": [],
            "autonomous_director.json": {}
        }
        for filename, default_val in autonomy_defaults.items():
            file_path = self.state_dir / filename
            if not file_path.exists():
                try:
                    file_path.write_text(json.dumps(default_val, indent=2), encoding="utf-8")
                except Exception as e:
                    pass

        
        # Thresholds
        self.CONFIDENCE_AUTO_THRESHOLD = 0.85
        self.RISK_LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        self.search_service = AISearchService(timeout=6)
        
        # Load environment
        load_sovereign_env()

    async def _query_ai_guarded(self, role: str, payload: Dict[str, Any], *, timeout: float = 35.0) -> Dict[str, Any]:
        """Bound AI calls so one slow provider cannot freeze the trading loop."""
        try:
            result = await asyncio.wait_for(query_ai(role, payload), timeout=timeout)
            return result if isinstance(result, dict) else {"is_fallback": True, "reason": "non_dict_ai_response"}
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Council AI timeout: {role} exceeded {timeout:.1f}s; using deterministic fallback.")
            return {"is_fallback": True, "reason": f"{role}_timeout"}
        except Exception as e:
            logger.warning(f"⚠️ Council AI error from {role}: {e}")
            return {"is_fallback": True, "reason": f"{role}_error:{e}"}

    def _load_whatif_snapshot(self) -> Dict[str, Any]:
        if not self.whatif_file.exists():
            return {"pairsSimulated": 0, "topOpportunities": [], "results": {}}
        try:
            with open(self.whatif_file, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.warning(f"Failed to load what-if snapshot: {e}")
        return {"pairsSimulated": 0, "topOpportunities": [], "results": {}}

    def _whatif_edge_score(self, whatif_snapshot: Dict[str, Any]) -> float:
        results = whatif_snapshot.get("results") if isinstance(whatif_snapshot, dict) else {}
        if not isinstance(results, dict) or not results:
            return 0.0
        best = 0.0
        positive = 0
        for item in results.values():
            if not isinstance(item, dict):
                continue
            ev = float(item.get("expectedValue") or 0.0)
            if ev > best:
                best = ev
            if ev > 0:
                positive += 1
        return min(1.0, max(0.0, best * 40.0) + min(0.25, positive * 0.04))

    def _evidence_floor(self, evidence_bundle: Dict[str, Any], whatif_snapshot: Dict[str, Any]) -> float:
        coverage = float(evidence_bundle.get("coverage_score") or 0.0)
        catalyst = float(evidence_bundle.get("catalyst_score") or 0.0)
        track = float(evidence_bundle.get("track_record_score") or 0.0)
        risk = float(evidence_bundle.get("risk_penalty") or 0.0)
        whatif_edge = self._whatif_edge_score(whatif_snapshot)

        floor = 0.78
        floor -= min(0.08, coverage * 0.05)
        floor -= min(0.08, catalyst * 0.06)
        floor -= min(0.06, track * 0.04)
        floor -= min(0.10, whatif_edge * 0.08)
        floor += min(0.08, risk * 0.06)
        return max(0.68, min(0.90, round(floor, 3)))

    def _now_wib(self) -> datetime:
        return datetime.now(WIB_TZ)

    def _minutes_to_midnight_wib(self, now: Optional[datetime] = None) -> int:
        now = now or self._now_wib()
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(0, int((next_midnight - now).total_seconds() // 60))

    def _deadline_pressure(self, minutes_to_midnight: int) -> float:
        """Normalize deadline pressure to [0, 1]. Pressure rises as midnight approaches."""
        return max(0.0, min(1.0, 1.0 - (minutes_to_midnight / 1440.0)))

    def _portfolio_context(self, signals_context: Dict[str, Any]) -> Dict[str, Any]:
        portfolio = dict(signals_context.get("portfolio_state") or {})
        open_positions = list(portfolio.get("active_positions") or [])
        combined_equity_idr = float(portfolio.get("combined_equity_idr") or 0.0)
        indodax_equity_idr = float(portfolio.get("equity_idr") or 0.0)
        if combined_equity_idr <= 0 and indodax_equity_idr > 0:
            combined_equity_idr = indodax_equity_idr
        daily_pnl_idr = float(portfolio.get("daily_pnl_idr") or portfolio.get("pnl_idr") or 0.0)
        daily_pnl_pct = float(portfolio.get("daily_pnl_pct") or portfolio.get("return_pct") or 0.0)
        if daily_pnl_pct == 0.0 and combined_equity_idr > 0 and daily_pnl_idr:
            daily_pnl_pct = (daily_pnl_idr / combined_equity_idr) * 100.0
        green_state = "GREEN" if daily_pnl_idr > 0 else "FLAT" if daily_pnl_idr == 0 else "RECOVERY"
        daily_state = dict(portfolio.get("daily_state") or {})
        if not daily_state:
            daily_state = {
                "color": green_state,
                "hold_winners": green_state == "GREEN",
                "take_profit_multiplier": 1.75 if green_state == "GREEN" else 1.0,
                "reason": "green_state" if green_state == "GREEN" else "recovery_state" if green_state == "RECOVERY" else "flat_state",
            }
        position_symbols = {
            str(pos.get("coin") or "").upper().replace("/IDR", "").replace("_IDR", "")
            for pos in open_positions
            if isinstance(pos, dict) and pos.get("coin")
        }
        return {
            "portfolio": portfolio,
            "combined_equity_idr": combined_equity_idr,
            "indodax_equity_idr": indodax_equity_idr,
            "daily_pnl_idr": daily_pnl_idr,
            "daily_pnl_pct": daily_pnl_pct,
            "green_state": green_state,
            "daily_state": daily_state,
            "open_positions": open_positions,
            "open_bets": [],
            "position_symbols": position_symbols,
            "has_positions": bool(open_positions),
        }

    def _normalize_signal_key(self, value: Any) -> str:
        text = str(value or "").upper().strip()
        if not text:
            return ""
        return (
            text.replace(" ", "")
            .replace("_", "/")
            .replace("::", ":")
            .replace("//", "/")
        )

    def _find_matching_signal(self, signals: List[Dict[str, Any]], target_ticker: str) -> Dict[str, Any]:
        norm_target = self._normalize_signal_key(target_ticker)
        if not norm_target:
            return {}
        target_base = norm_target.split("/")[0].split(":")[0]
        for signal in signals:
            if not isinstance(signal, dict):
                continue
            candidates = [
                signal.get("ticker"),
                signal.get("symbol"),
                signal.get("base_symbol"),
                signal.get("pair"),
                (signal.get("meta") or {}).get("market_id"),
            ]
            for candidate in candidates:
                norm_candidate = self._normalize_signal_key(candidate)
                if not norm_candidate:
                    continue
                candidate_base = norm_candidate.split("/")[0].split(":")[0]
                if (
                    norm_candidate == norm_target
                    or candidate_base == target_base
                    or norm_candidate.startswith(target_base)
                    or target_base in norm_candidate
                ):
                    return signal
        return {}

    def _decision_posture(
        self,
        decision: Dict[str, Any],
        evidence_bundle: Dict[str, Any],
        whatif_snapshot: Dict[str, Any],
        portfolio_ctx: Dict[str, Any],
        today_trade_activity: Dict[str, Any],
        minutes_to_midnight: int,
        confidence_floor: float,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "NONE").upper()
        confidence = float(decision.get("confidence", 0.0) or 0.0)
        coverage = float(evidence_bundle.get("coverage_score") or 0.0)
        catalyst = float(evidence_bundle.get("catalyst_score") or 0.0)
        track = float(evidence_bundle.get("track_record_score") or 0.0)
        risk = float(evidence_bundle.get("risk_penalty") or 0.0)
        whatif_edge = self._whatif_edge_score(whatif_snapshot)

        combined_equity_idr = float(portfolio_ctx.get("combined_equity_idr") or 0.0)
        daily_pnl_idr = float(portfolio_ctx.get("daily_pnl_idr") or 0.0)
        daily_pnl_pct = float(portfolio_ctx.get("daily_pnl_pct") or 0.0)
        green_state = str(portfolio_ctx.get("green_state") or ("GREEN" if daily_pnl_idr > 0 else "RECOVERY" if daily_pnl_idr < 0 else "FLAT")).upper()
        daily_state = dict(portfolio_ctx.get("daily_state") or {})
        has_positions = bool(portfolio_ctx.get("has_positions"))
        position_symbols = set(portfolio_ctx.get("position_symbols") or set())
        target_symbol = str(decision.get("ticker") or "").upper().split("/")[0].strip()
        target_symbol = target_symbol.replace("_IDR", "").replace("/IDR", "")
        has_target_position = target_symbol in position_symbols if target_symbol else False

        late_window = minutes_to_midnight <= 45
        time_pressure = 0.0 if minutes_to_midnight >= 180 else min(1.0, (180 - minutes_to_midnight) / 180.0)
        deadline_pressure = self._deadline_pressure(minutes_to_midnight)
        loss_pressure = 0.0
        if daily_pnl_pct < 0:
            loss_pressure = min(1.0, abs(daily_pnl_pct) / 1.5)

        evidence_strength = (
            0.34 * confidence
            + 0.18 * coverage
            + 0.11 * catalyst
            + 0.09 * track
            + 0.14 * whatif_edge
            - 0.14 * risk
        )
        evidence_strength += min(0.04, deadline_pressure * 0.03)
        recovery_mode = (
            daily_pnl_idr < 0
            and not late_window
            and confidence >= max(0.72, confidence_floor - 0.04)
            and coverage >= 0.38
            and risk <= 0.58
            and whatif_edge > 0.0
        )
        if recovery_mode:
            evidence_strength += min(0.06, (1.0 - loss_pressure) * 0.04)

        enter_threshold = confidence_floor if not recovery_mode else max(0.62, confidence_floor - 0.04)
        if not has_positions and minutes_to_midnight <= 720:
            enter_threshold = max(0.60, enter_threshold - min(0.04, deadline_pressure * 0.03))
        enter_score = max(0.0, min(1.0, evidence_strength))
        wait_score = max(0.0, min(1.0, 1.0 - enter_score + (0.08 if not action or action == "NONE" else 0.0)))
        exit_score = max(
            0.0,
            min(
                1.0,
                (0.30 * risk)
                + (0.18 * (1.0 - confidence))
                + (0.16 * (1.0 - whatif_edge))
                + (0.12 * time_pressure)
                + (0.18 * loss_pressure)
            ),
        )
        green_hold_mode = (
            green_state == "GREEN"
            and daily_pnl_idr > 0
            and not late_window
            and confidence >= max(confidence_floor, 0.72)
            and whatif_edge > 0.0
        )
        green_hold_reason = ""
        if green_hold_mode:
            hold_bonus = min(0.08, 0.02 + (confidence * 0.02) + (whatif_edge * 0.03) + (coverage * 0.01))
            evidence_strength = min(1.0, evidence_strength + hold_bonus)
            exit_discount = min(0.12, 0.04 + (confidence * 0.02) + (whatif_edge * 0.05))
            exit_score = max(0.0, exit_score - exit_discount)
            green_hold_reason = (
                f"green state active: preserve winners while edge remains strong ({daily_pnl_pct:+.2f}% daily)"
            )

        decision_state = "WAIT"
        decision_score = wait_score
        status = "WAIT"
        recovery_reason = ""
        learning_probe = bool(decision.get("learning_probe", False))
        trade_profile = str(decision.get("trade_profile", "STANDARD") or "STANDARD").upper()

        if action in {"BUY", "SELL"}:
            if action == "SELL" and not has_target_position:
                decision_state = "WAIT"
                decision_score = wait_score
                status = "WAIT"
                recovery_reason = "sell signal without matching inventory"
            elif action == "SELL" and green_hold_mode and has_target_position and exit_score < 0.82:
                decision_state = "WAIT"
                decision_score = max(wait_score, enter_score)
                status = "WAIT"
                recovery_reason = green_hold_reason or "green hold mode: keep winner alive"
            elif exit_score >= 0.72 and (late_window or risk >= 0.70 or daily_pnl_idr < 0):
                decision_state = "EXIT"
                decision_score = exit_score
                status = "EXECUTING" if action == "SELL" else "WAIT"
                recovery_reason = "risk-over-time exit posture"
            elif enter_score >= enter_threshold:
                decision_state = "ENTER"
                decision_score = enter_score
                status = "EXECUTING"
                if recovery_mode:
                    trade_profile = "RECOVERY"
                    recovery_reason = (
                        f"controlled recovery posture: pnl {daily_pnl_pct:+.2f}% with {minutes_to_midnight}m to midnight"
                    )
            elif action == "SELL" and has_target_position and exit_score >= 0.58:
                decision_state = "EXIT"
                decision_score = exit_score
                status = "EXECUTING"
            else:
                decision_state = "WAIT"
                decision_score = max(wait_score, 1.0 - enter_score)
                status = "WAIT"
        else:
            if exit_score >= 0.72 and has_positions and (late_window or risk >= 0.70 or daily_pnl_idr < 0):
                decision_state = "EXIT"
                decision_score = exit_score
                status = "WAIT"
                recovery_reason = "portfolio de-risk recommendation"
            else:
                decision_state = "WAIT"
                decision_score = wait_score
                status = "WAIT"

        if decision_state == "ENTER" and not recovery_mode and daily_pnl_idr < 0:
            trade_profile = "STANDARD"

        return {
            "status": status,
            "decision_state": decision_state,
            "decision_score": round(decision_score * 100.0, 1),
            "enter_score": round(enter_score * 100.0, 1),
            "wait_score": round(wait_score * 100.0, 1),
            "exit_score": round(exit_score * 100.0, 1),
            "recovery_mode": recovery_mode,
            "recovery_reason": recovery_reason,
            "confidence_floor": confidence_floor,
            "minutes_to_midnight": minutes_to_midnight,
            "daily_pnl_idr": daily_pnl_idr,
            "daily_pnl_pct": daily_pnl_pct,
            "combined_equity_idr": combined_equity_idr,
            "green_state": green_state,
            "daily_state": daily_state,
            "green_hold_mode": green_hold_mode,
            "green_hold_reason": green_hold_reason,
            "deadline_pressure": round(deadline_pressure, 3),
            "trade_profile": trade_profile,
            "learning_probe": learning_probe,
            "probe_confidence_floor": float(decision.get("probe_confidence_floor", 0.0) or 0.0),
        }

    def _signal_quality_score(self, signal: Dict[str, Any], whatif_snapshot: Dict[str, Any]) -> tuple[float, str]:
        """Local evidence scorer used when AI is slow/unavailable."""
        if not isinstance(signal, dict):
            return 0.0, "invalid_signal"
        symbol_text = str(signal.get("symbol") or signal.get("ticker") or "").upper()
        exchange = str(signal.get("exchange") or "").upper()
        if exchange and exchange != "INDODAX":
            return 0.0, f"fallback_unsupported_exchange:{exchange}"
        if symbol_text and not (symbol_text.endswith("/IDR") or symbol_text.endswith("_IDR")):
            return 0.0, f"fallback_requires_idr_pair:{symbol_text}"
        try:
            confidence = float(signal.get("confidence", 0.0) or 0.0)
            c5m = signal.get("change_5m_pct")
            change = abs(float(c5m)) if c5m is not None else 0.50
            vol_ratio = float(signal.get("vol_ratio", 1.0) or 1.0)
            spread = float(signal.get("spread_pct", 9.9) if signal.get("spread_pct") is not None else 9.9)
            tick = float(signal.get("tick_size_pct", 99.0) if signal.get("tick_size_pct") is not None else 99.0)
            levels = int(float(signal.get("price_levels_24h", 0) or 0))
        except Exception:
            return 0.0, "malformed_numeric_fields"

        market_quality = signal.get("market_quality") if isinstance(signal.get("market_quality"), dict) else {}
        if market_quality and market_quality.get("ok") is False:
            return 0.0, f"market_quality:{market_quality.get('reason')}"
        if tick > 3.0 or levels < 8:
            return 0.0, f"tick_trap tick={tick:.2f}% levels={levels}"
        if spread > 1.20:
            return 0.0, f"spread_too_wide {spread:.2f}%"
        if confidence <= 0:
            return 0.0, "missing_confidence"

        symbol = str(signal.get("symbol") or signal.get("ticker") or "").upper()
        base = symbol.split("/")[0].replace("_IDR", "")
        whatif_bonus = 0.0
        results = whatif_snapshot.get("results") if isinstance(whatif_snapshot, dict) else {}
        if isinstance(results, dict):
            for key, payload in results.items():
                if base and base in str(key).upper() and isinstance(payload, dict):
                    ev = float(payload.get("expectedValue") or 0.0)
                    whatif_bonus = min(0.08, max(0.0, ev * 8.0))
                    break

        stage = str(signal.get("pump_stage") or "").upper()
        stage_bonus = {
            "CONTINUATION": 0.055,
            "RECLAIM": 0.045,
            "RANGE_BREAK_RECLAIM": 0.050,
            "SUPPORT_BOUNCE": 0.040,
            "PIVOT_RECLAIM": 0.035,
            "MATURE": 0.025,
            "IGNITION": 0.020,
        }.get(stage, 0.0)

        spread_score = max(0.0, 1.0 - (spread / 1.20))
        score = (
            (confidence * 0.42)
            + (min(1.0, change / 4.0) * 0.16)
            + (min(1.0, max(0.0, vol_ratio - 1.0) / 2.5) * 0.12)
            + (spread_score * 0.12)
            + (min(1.0, levels / 30.0) * 0.06)
            + whatif_bonus
            + stage_bonus
        )
        return round(max(0.0, min(0.98, score)), 4), "ok"

    def _deterministic_trade_decision(
        self,
        signals_context: Dict[str, Any],
        evidence_bundle: Dict[str, Any],
        whatif_snapshot: Dict[str, Any],
        portfolio_ctx: Dict[str, Any],
        today_trade_activity: Dict[str, Any],
        minutes_to_midnight: int,
        confidence_floor: float,
        fallback_reason: str,
    ) -> Dict[str, Any]:
        """Make a bounded local decision when online AI deliberation cannot finish."""
        signals = [sig for sig in list(signals_context.get("signals") or []) if isinstance(sig, dict)]
        daily_context = signals_context.get("daily_context") if isinstance(signals_context.get("daily_context"), dict) else {}
        daily_color = str(daily_context.get("daily_color") or "FLAT").upper()
        ranked = []
        for signal in signals:
            score, reason = self._signal_quality_score(signal, whatif_snapshot)
            if score <= 0:
                ranked.append({"signal": signal, "score": score, "reject_reason": reason})
                continue
            ranked.append({"signal": signal, "score": score, "reject_reason": reason})

        ranked.sort(key=lambda row: row.get("score", 0.0), reverse=True)
        best = ranked[0] if ranked else {}
        best_signal = best.get("signal") if isinstance(best.get("signal"), dict) else {}
        best_score = float(best.get("score", 0.0) or 0.0)
        best_conf = float(best_signal.get("confidence", 0.0) or 0.0)
        has_trade_today = int(today_trade_activity.get("entries", 0) or 0) > 0
        deadline_pressure = self._deadline_pressure(minutes_to_midnight)
        adaptive_floor = confidence_floor
        if not has_trade_today and minutes_to_midnight <= 720:
            adaptive_floor = max(0.70, adaptive_floor - min(0.035, deadline_pressure * 0.04))
        if daily_color == "RECOVERY":
            adaptive_floor = max(0.56, adaptive_floor - 0.10)

        score_floor = 0.58
        conf_floor = max(0.70, adaptive_floor - 0.03)
        if daily_color == "RECOVERY":
            score_floor = 0.50
            conf_floor = max(0.60, adaptive_floor - 0.06)

        if (
            best_signal
            and best_score >= score_floor
            and best_conf >= conf_floor
            and float(evidence_bundle.get("risk_penalty", 0.0) or 0.0) <= 0.60
        ):
            symbol = str(best_signal.get("symbol") or best_signal.get("ticker") or "").upper()
            return {
                "status": "EXECUTING",
                "action": "BUY",
                "ticker": symbol,
                "confidence": round(max(best_conf, min(0.92, best_score)), 4),
                "logic": (
                    "deterministic fallback: signal passed tick/spread/history/what-if gates "
                    f"after AI fallback ({fallback_reason})"
                ),
                "source": "DETERMINISTIC_COUNCIL_FALLBACK",
                "fallback_decision": True,
                "ranked_candidates": ranked[:5],
            }

        return {
            "status": "WAIT",
            "action": "NONE",
            "ticker": str(best_signal.get("symbol") or "") if best_score > 0 else "",
            "confidence": round(best_conf, 4),
            "logic": f"deterministic fallback waited: no signal cleared local score/floor after {fallback_reason}",
            "wait_reason": (
                f"deterministic fallback waited: {best.get('reject_reason') or 'score/floor not cleared'}"
            ),
            "source": "DETERMINISTIC_COUNCIL_FALLBACK",
            "fallback_decision": True,
            "ranked_candidates": ranked[:5],
        }

    def _get_today_trade_activity(self) -> Dict[str, Any]:
        """Read today's trade activity so the council can avoid blind repetition."""
        try:
            from Core.Intelligence.kibot_learning_engine import get_engine

            engine = get_engine()
            closed_stats = engine.get_today_stats()
            activity = engine.get_today_activity() if hasattr(engine, "get_today_activity") else {}
            return {
                "entries": int(activity.get("entries", 0) or 0),
                "open": int(activity.get("open", 0) or 0),
                "closed": int(closed_stats.get("total", 0) or 0),
                "win_rate": float(closed_stats.get("win_rate", 0.5) or 0.5),
                "pnl_idr": float(closed_stats.get("pnl_idr", 0.0) or 0.0),
            }
        except Exception as e:
            logger.debug(f"Failed to load today trade activity: {e}")
            return {"entries": 0, "open": 0, "closed": 0, "win_rate": 0.5, "pnl_idr": 0.0}

    def _sanitize_indodax_strategy(self, candidate: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
        """Keep AI strategy useful without letting it lock the bot into hallucinated single-pair tunnel vision."""
        base = dict(current.get("indodax", {}) if isinstance(current.get("indodax"), dict) else {})
        if isinstance(candidate, dict):
            base.update(candidate)

        if os.getenv("KIBOT_ALLOW_AI_PAIR_LOCK", "0").strip().lower() not in {"1", "true", "yes", "on"}:
            base["allowed_pairs"] = ["*"]
            base["pairs"] = ["*"]

        fee_roundtrip = float(base.get("fee_roundtrip_pct", 1.02) or 1.02)
        take_profit = max(float(base.get("take_profit_pct", 1.5) or 1.5), fee_roundtrip + 0.30)
        base.update({
            "strategy": "PUMP_HUNTER",
            "buy_threshold_pct": max(0.30, min(float(base.get("buy_threshold_pct", 0.40) or 0.40), 1.20)),
            "trailing_stop_pct": max(0.25, min(float(base.get("trailing_stop_pct", 0.35) or 0.35), 1.20)),
            "hard_stop_pct": max(1.2, min(float(base.get("hard_stop_pct", 2.0) or 2.0), 3.0)),
            "max_exposure_idr": float(base.get("max_exposure_idr", 0) or 0),
            "max_slots": max(1, min(int(base.get("max_slots", 100) or 100), 100)),
            "min_confidence": max(0.70, min(float(base.get("min_confidence", 0.74) or 0.74), 0.88)),
            "take_profit_pct": round(take_profit, 3),
            "fee_roundtrip_pct": fee_roundtrip,
            "max_spread_pct": max(0.35, min(float(base.get("max_spread_pct", 0.55) or 0.55), 0.90)),
            "reject_tick_traps": True,
            "min_price_levels_24h": int(base.get("min_price_levels_24h", 8) or 8),
            "max_tick_size_pct": float(base.get("max_tick_size_pct", 3.0) or 3.0),
        })
        return base

    async def _build_trade_evidence(self, signals_context: Dict[str, Any]) -> Dict[str, Any]:
        signals = list(signals_context.get("signals") or [])
        targets = []
        seen = set()
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            symbol = str(sig.get("base_symbol") or sig.get("symbol") or "").upper().strip()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            targets.append(symbol)
        targets = targets[:3]

        if not targets:
            return {
                "targets": [],
                "coverage_score": 0.0,
                "catalyst_score": 0.0,
                "track_record_score": 0.0,
                "risk_penalty": 0.0,
                "sources": [],
                "notes": ["no target symbols available"],
            }

        evidence_rows: List[Dict[str, Any]] = []
        source_names = set()
        catalysts = 0
        red_flags = 0
        track_hits = 0
        track_total = 0

        async def gather_for_symbol(symbol: str) -> Dict[str, Any]:
            pair = f"{symbol.lower()}_idr"
            queries = [
                f"{symbol} crypto latest catalyst listing partnership exploit",
                f"{pair} track record volume trend Indodax",
                f"{symbol} site:coingecko.com crypto",
            ]
            async def safe(coro, default):
                try:
                    return await asyncio.wait_for(coro, timeout=5.5)
                except Exception:
                    return default

            tavily, serper, ddg, finnhub, brave, cryptopanic = await asyncio.gather(
                safe(self.search_service.tavily_search_async(queries[0], search_depth="advanced"), {}),
                safe(self.search_service.serper_search_async(queries[1]), {}),
                safe(self.search_service.ddg_search_async(queries[2], max_results=3), []),
                safe(self.search_service.finnhub_news_async(symbol.lower()), []),
                safe(self.search_service.brave_search_async(queries[0]), {}),
                safe(self.search_service.cryptopanic_news_async("hot"), []),
            )
            return {
                "symbol": symbol,
                "pair": pair,
                "tavily": tavily or {},
                "serper": serper or {},
                "ddg": ddg or [],
                "finnhub": finnhub or [],
                "brave": brave or {},
                "cryptopanic": cryptopanic or [],
            }

        try:
            symbol_payloads = await asyncio.wait_for(
                asyncio.gather(*(gather_for_symbol(symbol) for symbol in targets)),
                timeout=float(os.getenv("KIBOT_TRADE_EVIDENCE_TIMEOUT_SEC", "8.0") or 8.0),
            )
        except Exception as e:
            logger.warning(f"⚠️ Trade evidence timeout/error; using local signal evidence only: {e}")
            symbol_payloads = []

        for payload in symbol_payloads:
            symbol = payload.get("symbol")
            pair = payload.get("pair")
            texts: List[str] = []
            row_sources = set()
            for row in list(payload.get("finnhub") or [])[:3]:
                if isinstance(row, dict):
                    source_names.add("finnhub")
                    row_sources.add("finnhub")
                    title = str(row.get("headline") or row.get("title") or "").strip()
                    if title:
                        texts.append(title)
            tavily = payload.get("tavily") or {}
            if tavily:
                source_names.add("tavily")
                row_sources.add("tavily")
                ans = str(tavily.get("answer") or "").strip()
                if ans:
                    texts.append(ans)
                for item in list(tavily.get("results") or [])[:2]:
                    if isinstance(item, dict):
                        txt = str(item.get("content") or item.get("title") or "").strip()
                        if txt:
                            texts.append(txt)
            serper = payload.get("serper") or {}
            if serper:
                source_names.add("serper")
                row_sources.add("serper")
                for item in list(serper.get("organic") or [])[:2]:
                    if isinstance(item, dict):
                        txt = str(item.get("snippet") or item.get("title") or "").strip()
                        if txt:
                            texts.append(txt)
            for item in list(payload.get("ddg") or [])[:2]:
                if isinstance(item, dict):
                    source_names.add("ddg")
                    row_sources.add("ddg")
                    txt = str(item.get("body") or item.get("title") or "").strip()
                    if txt:
                        texts.append(txt)
            brave = payload.get("brave") or {}
            if brave:
                source_names.add("brave")
                row_sources.add("brave")
                for item in list((brave.get("web") or {}).get("results") or [])[:2]:
                    if isinstance(item, dict):
                        txt = str(item.get("description") or item.get("title") or "").strip()
                        if txt:
                            texts.append(txt)
            for item in list(payload.get("cryptopanic") or [])[:3]:
                if isinstance(item, dict):
                    source_names.add("cryptopanic")
                    row_sources.add("cryptopanic")
                    title = str(item.get("title") or "").strip()
                    if title:
                        texts.append(title)

            combined = " ".join(texts).lower()
            catalyst_hit = any(key in combined for key in (
                "listing", "mainnet", "partnership", "upgrade", "launch", "integrat", "airdrop", "etf", "approval"
            ))
            exploit_hit = any(key in combined for key in (
                "hack", "exploit", "rug", "lawsuit", "ban", "delist", "halt", "outage"
            ))
            track_hit = any(key in combined for key in ("volume", "liquidity", "trend", "history", "record"))

            if catalyst_hit:
                catalysts += 1
            if exploit_hit:
                red_flags += 1
            if track_hit:
                track_hits += 1
            track_total += 1

            evidence_rows.append({
                "symbol": symbol,
                "pair": pair,
                "source_count": len(row_sources),
                "catalyst_hit": catalyst_hit,
                "risk_hit": exploit_hit,
                "track_hit": track_hit,
                "summary": texts[:6],
            })

        coverage_score = min(1.0, len(source_names) / 5.0)
        catalyst_score = min(1.0, catalysts / max(1, len(symbol_payloads)))
        track_record_score = min(1.0, track_hits / max(1, track_total))
        risk_penalty = min(1.0, red_flags / max(1, len(symbol_payloads)))

        return {
            "targets": targets,
            "coverage_score": round(coverage_score, 3),
            "catalyst_score": round(catalyst_score, 3),
            "track_record_score": round(track_record_score, 3),
            "risk_penalty": round(risk_penalty, 3),
            "sources": sorted(source_names),
            "evidence_rows": evidence_rows,
            "notes": [
                "broadened validation across Tavily, Serper, Brave, DDG, Finnhub, and CryptoPanic",
                "track record proxy uses repeated mentions of volume, liquidity, history, and trend",
            ],
        }

    async def deliberate_system(self, issue_context: Dict) -> Dict:
        """Handles system anomalies and self-healing logic (Watchman mode)."""
        logger.info(f"🏛️ Council deliberating system issue: {issue_context.get('type')}")
        snapshot = issue_context.get("snapshot", {})
        
        # 1. OBSERVATION (Watchman)
        obs_res = await query_ai("COUNCIL_WATCHMAN", {"snapshot": snapshot})
        if not obs_res or obs_res.get("status") == "NORMAL":
            if issue_context.get("type") != "EMERGENCY":
                return {"action": "NONE", "confidence": 1.0}

        # 2. STRATEGY (Strategist)
        strat_res = await query_ai("COUNCIL_STRATEGIST", {
            "context": issue_context,
            "diagnosis": obs_res
        })
        
        decision = {
            "type": "SYSTEM_ACTION",
            "issue": issue_context.get("type"),
            "action": strat_res.get("action", "NONE") if isinstance(strat_res, dict) else "NONE",
            "reasoning": strat_res.get("reasoning", "No AI response") if isinstance(strat_res, dict) else "ERROR",
            "confidence": strat_res.get("confidence", 0.0) if isinstance(strat_res, dict) else 0.0,
            "timestamp": time.time()
        }
        self._log_decision(decision)
        return decision

    async def run_strategic_planning(self, market_snapshot: Dict):
        """
        The 5-minute strategic debate.
        Inputs: Market Data, System Health.
        Output: New strategy parameters in active_strategy.json.
        """
        logger.info("🏛️ Council Strategic Session: Formulating new posture...")
        
        # 1. Gather Intelligence
        # We call System Engineer first for health check
        sys_stats = market_snapshot.get("system_stats", {}).get("BATAM_MASTER", {})
        cpu = sys_stats.get('cpu', 0)
        ram = sys_stats.get('ram', 0)
        disk = sys_stats.get('disk', 0)
        
        # [SAFEGUARD] If usage is low, skip AI deliberation to avoid hallucinations
        if cpu < 80 and ram < 85:
            logging.info("🛡️ [SAFEGUARD] System resources low. Skipping AI health deliberation.")
            health = {"health_status": "STABLE", "action": "NONE", "reason": "System resources within safe limits (Auto-Stable)"}
        else:
            health_context = f"CPU: {cpu}%, MEM: {ram}%, DISK: {disk}%"
            health = await self._query_ai_guarded("SYSTEM_ENGINEER", {"netdata_snapshot": health_context}, timeout=12)
        
        if health and health.get("action") == "PAUSE":
            cpu_critical = float(cpu) >= 95.0
            ram_critical = float(ram) >= 90.0
            disk_critical = float(disk) >= 95.0
            if not ((cpu_critical and ram_critical) or disk_critical):
                logger.warning(
                    "🛡️ [SAFEGUARD] SystemEngineer requested PAUSE on CPU-only spike; "
                    "overriding to DEGRADED/NONE so trading can continue under guardrails."
                )
                health = {
                    "health_status": "DEGRADED",
                    "action": "NONE",
                    "reason": "CPU spike without memory/disk exhaustion; continue with guardrails.",
                }
            else:
                set_urgency("EMERGENCY_PAUSE", health.get("reason"))
                return {"status": "PAUSED", "reason": health.get("reason")}

        # 2. Market Synthesis
        scout_res = await self._query_ai_guarded("MARKET_SCOUT", {"raw_scan_results": market_snapshot}, timeout=15)
        sentiment = await self._query_ai_guarded("SENTIMENT_SYNTHESIZER", {"news_context": "Global Crypto Trends"}, timeout=15)
        whatif_snapshot = self._load_whatif_snapshot()
        portfolio_ctx = self._portfolio_context(market_snapshot)

        # [NEW V3.1] Forensic intelligence
        whale_intel = await self._query_ai_guarded("WHALE_WATCHER", {"orderbook_snapshot": market_snapshot.get("indodax")}, timeout=12)

        # 3. Final Strategic Decision (Strategy Dean)
        current = load_strategy()
        pnl_history = load_pnl_history()
        runtime_daily_state = current.get("daily_state") if isinstance(current.get("daily_state"), dict) else portfolio_ctx.get("daily_state", {})
        
        # [MIDNIGHT ORACLE LOGIC]
        now = self._now_wib()
        # If between 23:45 and 00:00, force 'EXIT_ALL' mode
        is_midnight_approaching = (now.hour == 23 and now.minute >= 45)
        minutes_to_midnight = self._minutes_to_midnight_wib()
        deadline_pressure = self._deadline_pressure(minutes_to_midnight)

        antagonist_view = await self._query_ai_guarded("COUNCIL_ANTAGONIST", {
            "signals": market_snapshot.get("signals", market_snapshot),
            "evidence_bundle": market_snapshot.get("evidence_bundle", {}),
            "whatif_snapshot": whatif_snapshot,
            "portfolio_state": portfolio_ctx.get("portfolio", {}),
            "daily_state": runtime_daily_state,
            "today_trade_activity": self._get_today_trade_activity(),
            "minutes_to_midnight": minutes_to_midnight,
            "deadline_pressure": deadline_pressure,
            "current_strategy": current,
        }, timeout=35)
        possibility_view = await self._query_ai_guarded("POSSIBILITY_MINING", {
            "raw_data": market_snapshot,
            "current_strategy": current,
            "daily_state": runtime_daily_state,
            "deadline_pressure": deadline_pressure,
            "minutes_to_midnight": minutes_to_midnight,
        }, timeout=35)
        
        dean_res = await self._query_ai_guarded("STRATEGY_DEAN", {
            "market_data": scout_res,
            "system_health": health,
            "current_strategy": current,
            "sentiment": sentiment,
            "whale_intel": whale_intel,
            "whatif_snapshot": whatif_snapshot,
            "daily_state": runtime_daily_state,
            "recent_pnl": pnl_history,
            "is_midnight_approaching": is_midnight_approaching,
            "minutes_to_midnight": minutes_to_midnight,
            "deadline_pressure": deadline_pressure,
            "antagonist_view": antagonist_view,
            "possibility_view": possibility_view,
            "philosophy": "ORGANIZED_GREED" # Never satisfied
        }, timeout=60)

        if not isinstance(dean_res, dict):
            logger.error(f"❌ [FATAL] AI Strategy Dean returned invalid response type: {type(dean_res)}")
            return {"status": "FAILED", "reason": "AI strategy generation failed - invalid type"}

        if dean_res.get("is_fallback"):
            logger.warning(
                "⏱️ Strategy Dean unavailable; preserving current strategy instead of hallucinating a new posture."
            )
            return {"status": "SKIPPED", "reason": dean_res.get("reason", "strategy_dean_unavailable")}

        if dean_res:
            raw_mode = str(dean_res.get("global_mode", "NEUTRAL")).upper().strip()
            if raw_mode == "EXIT_ALL" and not is_midnight_approaching:
                current_mode = str(current.get("global_mode", "NEUTRAL")).upper().strip()
                daily_color = str(runtime_daily_state.get("color", "FLAT")).upper().strip()
                if daily_color == "GREEN":
                    raw_mode = "CONTROLLED_AGGRESSIVE"
                elif daily_color == "RECOVERY":
                    raw_mode = current_mode if current_mode not in {"EXIT_ALL", ""} else "NEUTRAL"
                else:
                    raw_mode = current_mode if current_mode not in {"EXIT_ALL", ""} else "NEUTRAL"
                logger.warning(
                    "🛡️ Premature EXIT_ALL overridden outside midnight window; "
                    f"using {raw_mode} instead."
                )
            elif raw_mode == "DEFENSIVE" and not is_midnight_approaching:
                current_mode = str(current.get("global_mode", "NEUTRAL")).upper().strip()
                daily_color = str(runtime_daily_state.get("color", "FLAT")).upper().strip()
                cpu_safe = float(cpu) < 80.0
                ram_safe = float(ram) < 85.0
                disk_safe = float(disk) < 90.0
                if daily_color == "FLAT" and cpu_safe and ram_safe and disk_safe:
                    raw_mode = "CONTROLLED_AGGRESSIVE"
                    logger.warning(
                        "🛡️ Defensive posture softened on healthy FLAT day; "
                        f"using {raw_mode} to keep the council opportunistic."
                    )
                elif daily_color == "GREEN":
                    raw_mode = "CONTROLLED_AGGRESSIVE"
                elif daily_color == "RECOVERY" and current_mode not in {"EXIT_ALL", ""}:
                    raw_mode = current_mode
            new_strategy = {
                "version": "3.0.0",
                "global_mode": raw_mode,
                "indodax": self._sanitize_indodax_strategy(dean_res.get("indodax", {}), current),
                "antagonist_view": antagonist_view,
                "possibility_view": possibility_view,
                "deadline_pressure": deadline_pressure,
                "daily_state": runtime_daily_state,
                "last_updated": time.time()
            }
            save_strategy(new_strategy)
            logger.info(f"✅ Strategic Posture Updated: {new_strategy['global_mode']}")
            return {"status": "SUCCESS", "mode": new_strategy['global_mode']}
        
        return {"status": "FAILED", "reason": "AI strategy generation failed"}
        
    async def monitor_active_position(self, ticker: str, entry_price: float):
        """
        War Room mode for active trades.
        """
        logger.info(f"🛡️ Active Guardian: Protecting {ticker}...")
        res = await query_ai("ACTIVE_GUARDIAN", {"ticker": ticker, "entry_price": entry_price})
        
        if res and res.get("status") == "EXIT":
            # Force emergency exit by updating strategy or sending urgency
            logger.warning(f"🚨 GUARDIAN ORDERED EXIT: {ticker} - {res.get('reasoning')}")
            set_urgency("FORCE_EXIT", f"Guardian: {res.get('reasoning')}")

    async def deliberate_trading(self, signals_context: Dict) -> Dict:
        """
        [NEW V3.2] Trading Deliberation for MasterNode.
        Analyzes incoming signals and returns a formal mandate for execution.
        """
        logger.info(f"🏛️ Council Deliberating Trading Signals...")

        # Phase 3 & 4: Autonomous Director Intelligence Gate Integration
        try:
            from Core.Intelligence.autonomous_director import AutonomousDirector
            import json
            
            regime = (signals_context.get("market_context") or {}).get("regime") if isinstance(signals_context.get("market_context"), dict) else "UNKNOWN"
            director = AutonomousDirector(market_regime=regime or "UNKNOWN")
            
            raw_candidates = list(signals_context.get("signals") or [])
            evaluation = director.evaluate_cycle(raw_candidates)
            
            # Persist separate state output JSON files as mandated in Phase 4
            self.state_dir.mkdir(parents=True, exist_ok=True)
            
            # 1. autonomous_director.json
            (self.state_dir / "autonomous_director.json").write_text(
                json.dumps(evaluation, indent=2, default=str),
                encoding="utf-8"
            )
            
            # 2. signal_quality.json
            sq_list = [c.get("signal_quality") for c in raw_candidates if c.get("signal_quality")]
            (self.state_dir / "signal_quality.json").write_text(
                json.dumps(sq_list, indent=2, default=str),
                encoding="utf-8"
            )
            
            # 3. expected_value.json
            ev_list = [c.get("ev_analysis") for c in raw_candidates if c.get("ev_analysis")]
            (self.state_dir / "expected_value.json").write_text(
                json.dumps(ev_list, indent=2, default=str),
                encoding="utf-8"
            )
            
            # 4. strategy_scorecard.json
            scorecard_list = [c.get("scorecard") for c in raw_candidates if c.get("scorecard")]
            (self.state_dir / "strategy_scorecard.json").write_text(
                json.dumps(scorecard_list, indent=2, default=str),
                encoding="utf-8"
            )

            best_action = "WAIT"
            venue = "indodax"
            reason = "no approved candidate"
            confidence = 0.0
            evidence_bundle: Dict[str, Any] = {}
            if isinstance(evaluation, dict):
                if evaluation.get("live_forward"):
                    best_action = "ENTER"
                    reason = "approved candidate ready for live forward"
                    top = evaluation["live_forward"][0] or {}
                elif evaluation.get("approved"):
                    best_action = "WAIT"
                    reason = "approved but live gate off"
                    top = evaluation["approved"][0] or {}
                else:
                    top = {}
                confidence = float(
                    top.get("scorecard", {}).get("composite_score", 0.0)
                    or top.get("confidence", 0.0)
                    or 0.0
                )
                venue = str(top.get("venue") or top.get("exchange") or "indodax").lower()

            minutes_to_midnight = self._minutes_to_midnight_wib()
            decision_trace = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "objective": "maximize_risk_adjusted_profit_for_boss",
                "market_summary": str(regime or "UNKNOWN"),
                "best_action": best_action,
                "venue": venue,
                "reason": reason,
                "confidence": round(confidence, 4),
                "risk_status": str((evidence_bundle.get("risk_status") or {}).get("state") or "UNKNOWN"),
                "next_check_seconds": int(max(10, min(300, (minutes_to_midnight or 1) * 60))),
            }
            (self.state_dir / "ai_decision_trace.json").write_text(
                json.dumps(decision_trace, indent=2, default=str),
                encoding="utf-8",
            )
            
            logger.info("✅ Autonomous Intelligence Gates executed & persisted successfully.")
        except Exception as _director_err:
            logger.error(f"❌ Autonomous Intelligence integration failed: {_director_err}")
            evaluation = {}

        whatif_snapshot = self._load_whatif_snapshot()
        evidence_bundle = await self._build_trade_evidence(signals_context)
        today_trade_activity = self._get_today_trade_activity()
        portfolio_ctx = self._portfolio_context(signals_context)
        minutes_to_midnight = self._minutes_to_midnight_wib()
        deadline_pressure = self._deadline_pressure(minutes_to_midnight)

        portfolio_live = portfolio_ctx.get("portfolio", {}) if isinstance(portfolio_ctx.get("portfolio"), dict) else {}
        realized_raw = portfolio_live.get("realized_pnl_idr")
        unrealized_raw = portfolio_live.get("unrealized_pnl_idr")
        if realized_raw is None and unrealized_raw is None:
            realized_pnl = float(portfolio_ctx.get("daily_pnl_idr", 0.0) or 0.0)
            unrealized_pnl = 0.0
        else:
            realized_pnl = float(realized_raw or 0.0)
            unrealized_pnl = float(unrealized_raw or 0.0)

        daily_context = get_daily_context(
            realized_pnl_idr=realized_pnl,
            unrealized_pnl_idr=unrealized_pnl,
            combined_equity_idr=float(portfolio_ctx.get("combined_equity_idr", 0.0) or 0.0),
            available_cash_idr=float(portfolio_live.get("idr_cash", 0.0) or 0.0),
            current_positions=portfolio_ctx.get("open_positions", []),
            market_regime=(signals_context.get("market_context") or {}).get("regime") if isinstance(signals_context.get("market_context"), dict) else None,
        )

        heatmap = load_heatmap(default_fetch=False)
        order_summary = {}
        try:
            from Core.Intelligence.order_tracker import get_tracker as _get_ot

            order_summary = _get_ot().get_today_summary()
        except Exception:
            order_summary = {}
        green_probability = estimate_green_probability(
            daily_context=daily_context,
            heatmap=heatmap,
            candidates=list(signals_context.get("signals") or []),
            order_summary=order_summary,
            system_health=signals_context.get("system_health") or {},
            source_health={
                "coverage_score": evidence_bundle.get("coverage_score", 0.0),
                "risk_penalty": evidence_bundle.get("risk_penalty", 0.0),
                "source_count": len(evidence_bundle.get("sources") or []),
            },
        )
        try:
            (self.state_dir / "green_probability.json").write_text(
                json.dumps(green_probability, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as _gp_err:
            logger.debug(f"Failed to persist green probability: {_gp_err}")

        signals_context = {
            **signals_context,
            "whatif_snapshot": whatif_snapshot,
            "evidence_bundle": evidence_bundle,
            "today_trade_activity": today_trade_activity,
            "portfolio_state": portfolio_ctx.get("portfolio", {}),
            "daily_state": portfolio_ctx.get("daily_state", {}),
            "daily_context": daily_context,
            "market_heatmap": heatmap,
            "green_probability": green_probability,
            "order_summary": order_summary,
            "minutes_to_midnight": minutes_to_midnight,
            "deadline_pressure": deadline_pressure,
        }
        
        # [REFINED] Script-Only Hot-Path: Evaluate via DecisionAuthority
        try:
            from Core.Decision.decision_authority import DecisionAuthority
            da = DecisionAuthority(state_dir=self.state_dir)
            decision = da.evaluate(signals_context)
            logger.info(f"✅ [SCRIPT-ONLY HOT-PATH] Evaluated via DecisionAuthority: action={decision.get('action')}, ticker={decision.get('ticker')}")
        except Exception as da_err:
            logger.warning(f"⚠️ DecisionAuthority failed, falling back to local deterministic: {da_err}")
            decision = self._deterministic_trade_decision(
                signals_context=signals_context,
                evidence_bundle=evidence_bundle,
                whatif_snapshot=whatif_snapshot,
                portfolio_ctx=portfolio_ctx,
                today_trade_activity=today_trade_activity,
                minutes_to_midnight=minutes_to_midnight,
                confidence_floor=self._evidence_floor(evidence_bundle, whatif_snapshot),
                fallback_reason=f"DecisionAuthority error: {da_err}",
            )

        # AI Deliberation is processed purely out-of-band/background to generate strategy reviews
        # and propose adaptive parameters via `state/ai_strategy_review.json`
        asyncio.create_task(self.run_background_ai_review(signals_context, decision))
        
        # Initialize default mock antagonist_view so subsequent telemetry / logic doesn't break
        antagonist_view = {"review": "Passive background review scheduled."}

        # 2. Add metadata and match source signal
        decision["timestamp"] = time.time()
        decision["whatif_snapshot"] = whatif_snapshot
        decision["evidence_bundle"] = evidence_bundle
        decision["antagonist_view"] = antagonist_view or {}
        decision["deadline_pressure"] = deadline_pressure
        decision["daily_state"] = portfolio_ctx.get("daily_state", {})
        confidence_floor = self._evidence_floor(evidence_bundle, whatif_snapshot)

        # [REFINED V3.3] Strict Midnight WIB Hard Gate (§11.2)
        # If GREEN and close to midnight, we stop almost everything.
        if (
            daily_context.get("daily_color") == "GREEN"
            and daily_context.get("urgency_level") in ("HIGH", "CRITICAL")
            and float(decision.get("confidence", 0.0) or 0.0) < 0.96
        ):
            logger.info("🛡️ Midnight Protocol: LOCK_GREEN active. Rebuffing non-exceptional signals.")
            decision.update({
                "action": "NONE",
                "status": "WAIT",
                "decision_state": "WAIT",
                "wait_reason": "LOCK_GREEN: protecting daily profit before midnight deadline"
            })

        # If the speaker says WAIT but the scanner has a clearly ranked A/B
        # candidate, promote it into the formal role contract instead of letting
        # the system sit blind. The Fast+Deep Council below can still veto.
        if str(decision.get("action") or "NONE").upper() not in {"BUY", "SELL"}:
            candidates = [
                s for s in list(signals_context.get("signals") or [])
                if isinstance(s, dict) and str(s.get("exchange") or "INDODAX").upper() == "INDODAX"
            ]
            candidates.sort(
                key=lambda s: float(s.get("opportunity_score") or s.get("confidence") or 0.0),
                reverse=True,
            )
            best_candidate = candidates[0] if candidates else {}
            best_conf = float(best_candidate.get("confidence", 0.0) or 0.0) if best_candidate else 0.0
            best_grade = str(best_candidate.get("trade_grade") or "C").upper()
            best_lifecycle = str(best_candidate.get("lifecycle") or best_candidate.get("pump_stage") or "").upper()
            if (
                best_candidate
                and best_conf >= max(0.68, confidence_floor - 0.04)
                and best_grade in {"A", "B"}
                and best_lifecycle not in {"TRAP", "LOCAL_TRAP", "DISTRIBUTION"}
                and daily_context.get("allowed_risk_mode") != "WAIT"
            ):
                decision.update({
                    "action": "BUY",
                    "ticker": str(best_candidate.get("symbol") or best_candidate.get("ticker") or "").upper(),
                    "confidence": max(float(decision.get("confidence", 0.0) or 0.0), best_conf),
                    "logic": "scanner opportunity override routed to formal Fast+Deep Council",
                    "source": "SCANNER_OPPORTUNITY_OVERRIDE",
                    "fallback_decision": bool(decision.get("fallback_decision", False)),
                })
        
        # Find matching signal from context for price/metadata parity
        signals = signals_context.get("signals", [])
        target_ticker = str(decision.get("ticker") or "UNKNOWN").upper()
        source_signal = self._find_matching_signal(signals, target_ticker)
        decision["source_signal"] = source_signal

        # 2b. Formal Fast+Deep Council contract for any candidate that might
        # touch money. This makes the role debate deterministic and auditable
        # even when the speaker model is over-eager.
        two_phase_mandate: Dict[str, Any] = {}
        exit_plan: Dict[str, Any] = {}
        if (
            isinstance(source_signal, dict)
            and source_signal
            and str(decision.get("action") or "").upper() in {"BUY", "SELL"}
        ):
            try:
                from Core.risk_gate import RiskGate

                capital_state = RiskGate().get_capital_state(
                    float(portfolio_live.get("idr_cash", 0.0) or 0.0),
                    active_slots=len(portfolio_ctx.get("open_positions") or []),
                )
            except Exception:
                capital_state = {"capital_state": "NORMAL", "sizing_mode": "NORMAL"}

            pair_memory = source_signal.get("historian_profile") if isinstance(source_signal.get("historian_profile"), dict) else {}
            try:
                exit_plan = build_exit_plan(
                    source_signal,
                    daily_context,
                    str(capital_state.get("capital_state", "NORMAL")),
                    pair_memory,
                )
            except Exception as ep_err:
                exit_plan = {"error": str(ep_err), "pair": source_signal.get("symbol")}

            try:
                two_phase_mandate = await self.council_mandate(
                    source_signal,
                    daily_context,
                    capital_state=capital_state,
                    exit_plan=exit_plan,
                    pair_memory=pair_memory,
                )
            except Exception as mandate_err:
                logger.warning(f"Fast+Deep Council contract failed; using speaker decision: {mandate_err}")
                two_phase_mandate = {"phase": "CONTRACT_ERROR", "reason": str(mandate_err)}

            decision["two_phase_council"] = two_phase_mandate
            decision["exit_plan"] = exit_plan
            if two_phase_mandate and two_phase_mandate.get("decision_state") != "ENTER":
                decision["status"] = "WAIT"
                decision["decision_state"] = "WAIT"
                decision["action"] = "NONE"
                decision["confidence"] = min(
                    float(decision.get("confidence", 0.0) or 0.0),
                    float(two_phase_mandate.get("confidence", 0.0) or 0.0),
                )
                decision["wait_reason"] = (
                    f"{two_phase_mandate.get('phase', 'COUNCIL')} veto by "
                    f"{two_phase_mandate.get('veto_by') or 'role'}: "
                    f"{two_phase_mandate.get('reason')}"
                )
            elif two_phase_mandate and two_phase_mandate.get("decision_state") == "ENTER":
                decision["confidence"] = max(
                    float(decision.get("confidence", 0.0) or 0.0),
                    float(two_phase_mandate.get("confidence", 0.0) or 0.0),
                )
                decision["trade_grade"] = two_phase_mandate.get("trade_grade", source_signal.get("trade_grade"))
                decision["budget_fraction"] = two_phase_mandate.get("budget_fraction")
                decision["capital_state"] = two_phase_mandate.get("capital_state")
                decision["deadline_mode"] = two_phase_mandate.get("deadline_mode")
                decision["confidence_breakdown"] = two_phase_mandate.get("breakdown", source_signal.get("confidence_breakdown", {}))

        # 3. Determine Execution Status
        decision["confidence_floor"] = confidence_floor
        decision["today_trade_activity"] = today_trade_activity
        decision["portfolio_state"] = portfolio_ctx.get("portfolio", {})
        decision["daily_context"] = daily_context
        decision["market_heatmap"] = {
            "market_breadth": heatmap.get("market_breadth"),
            "green_pairs": heatmap.get("green_pairs"),
            "red_pairs": heatmap.get("red_pairs"),
            "pump_candidates": heatmap.get("pump_candidates"),
            "local_pump_candidates": heatmap.get("local_pump_candidates"),
            "top_movers": list(heatmap.get("top_movers") or [])[:5],
        }
        decision["green_probability"] = green_probability
        if isinstance(source_signal, dict):
            decision["fallback_category"] = source_signal.get("fallback_category")
            decision["category_policy"] = source_signal.get("category_policy", {})
        decision["unit_price_rule"] = {
            "must_be_below_total_equity": True,
            "basis": "total_equity_idr",
            "enforced_by": ["RiskGate", "IndodaxExecutor"],
        }
        decision.setdefault("learning_probe", False)
        decision.setdefault("trade_profile", "STANDARD")

        has_trade_today = int(today_trade_activity.get("entries", 0) or 0) > 0
        probe_floor = max(0.72, confidence_floor - 0.05)
        probe_ready = (
            decision.get("action") in ["BUY", "SELL"]
            and not has_trade_today
            and float(decision.get("confidence", 0) or 0) >= probe_floor
            and float(evidence_bundle.get("coverage_score", 0) or 0) >= 0.35
            and float(evidence_bundle.get("risk_penalty", 0) or 0) <= 0.6
            and self._whatif_edge_score(whatif_snapshot) > 0.0
        )

        posture = self._decision_posture(
            decision=decision,
            evidence_bundle=evidence_bundle,
            whatif_snapshot=whatif_snapshot,
            portfolio_ctx=portfolio_ctx,
            today_trade_activity=today_trade_activity,
            minutes_to_midnight=minutes_to_midnight,
            confidence_floor=confidence_floor,
        )

        decision.update(posture)
        decision["deadline_pressure"] = deadline_pressure
        decision["deadline_mode"] = decision.get("deadline_mode") or daily_context.get("deadline_mode")
        
        if antagonist_view and isinstance(antagonist_view, dict):
            decision["antagonist_view"] = antagonist_view
            best_alt_action = str(antagonist_view.get("best_alternative_action") or "NONE").upper()
            best_alt_ticker = str(antagonist_view.get("best_alternative_ticker") or "").upper()
            best_alt_conf = float(antagonist_view.get("best_alternative_confidence", 0.0) or 0.0)
            alt_threshold = max(confidence_floor, 0.74)
            if str(daily_context.get("daily_color") or "").upper() == "RECOVERY":
                alt_threshold = max(0.62, confidence_floor - 0.08)
            if (
                decision.get("decision_state") == "WAIT"
                and not (isinstance(decision.get("two_phase_council"), dict) and decision["two_phase_council"].get("veto_by"))
                and best_alt_action in {"BUY", "SELL"}
                and best_alt_ticker
                and best_alt_conf >= alt_threshold
                and minutes_to_midnight > 30
            ):
                decision["decision_state"] = "ENTER"
                decision["action"] = best_alt_action
                decision["ticker"] = best_alt_ticker
                decision["confidence"] = max(float(decision.get("confidence", 0.0) or 0.0), best_alt_conf)
                decision["status"] = "EXECUTING"
                decision["trade_profile"] = "RECOVERY" if decision.get("recovery_mode") else decision.get("trade_profile", "STANDARD")
                decision["source_signal"] = self._find_matching_signal(signals, best_alt_ticker)
                decision["wait_reason"] = (
                    f"antagonist pivot to {best_alt_ticker} with confidence {best_alt_conf:.3f}"
                )

        if decision.get("status") == "EXECUTING" and not decision.get("source_signal"):
            decision["status"] = "WAIT"
            decision["decision_state"] = "WAIT"
            decision["wait_reason"] = "no matching source signal for selected mandate"

        if decision.get("status") == "EXECUTING" and decision.get("decision_state") == "ENTER" and probe_ready:
            decision["learning_probe"] = True
            decision["trade_profile"] = "LEARNING_PROBE" if decision.get("trade_profile") == "STANDARD" else decision["trade_profile"]
            decision["probe_confidence_floor"] = probe_floor
            decision["wait_reason"] = (
                f"learning probe triggered: confidence {decision.get('confidence', 0):.3f} >= probe floor {probe_floor:.3f}"
            )
        elif decision.get("status") == "WAIT" and decision.get("decision_state") == "WAIT":
            if decision.get("fallback_decision") and decision.get("wait_reason"):
                decision["wait_reason"] = str(decision.get("wait_reason"))
            elif decision.get("recovery_mode"):
                decision["wait_reason"] = (
                    f"recovery posture active: pnl {decision.get('daily_pnl_pct', 0):+.2f}% with {decision.get('minutes_to_midnight', 0)}m to midnight"
                )
            else:
                decision["wait_reason"] = (
                    f"confidence {decision.get('confidence', 0):.3f} below floor {confidence_floor:.3f}"
                )
        elif decision.get("decision_state") == "EXIT" and decision.get("status") != "EXECUTING":
            decision["wait_reason"] = (
                f"exit posture signaled: score {decision.get('exit_score', 0):.1f}"
            )

        source_signal = decision.get("source_signal") if isinstance(decision.get("source_signal"), dict) else {}
        two_phase = decision.get("two_phase_council") if isinstance(decision.get("two_phase_council"), dict) else {}
        decision["role_votes"] = [
            {
                "role": "Hunter",
                "vote": "PASS" if float(source_signal.get("confidence", decision.get("confidence", 0)) or 0) >= 0.60 else "WAIT",
                "reason": f"signal confidence {float(source_signal.get('confidence', decision.get('confidence', 0)) or 0):.3f}",
            },
            {
                "role": "LiquidityEngineer",
                "vote": "PASS" if source_signal and float(source_signal.get("spread_pct", 0.0) or 0.0) <= 1.20 else "WAIT",
                "reason": f"spread {float(source_signal.get('spread_pct', 0.0) or 0.0):.2f}%",
            },
            {
                "role": "Historian",
                "vote": (source_signal.get("historian_profile") or {}).get("verdict", "UNKNOWN") if isinstance(source_signal.get("historian_profile"), dict) else "UNKNOWN",
                "reason": "pair memory verdict",
            },
            {
                "role": "DeadlineKeeper",
                "vote": daily_context.get("deadline_mode", "PATIENT"),
                "reason": f"{daily_context.get('minutes_to_midnight')}m left, color={daily_context.get('daily_color')}",
            },
            {
                "role": "Antagonist",
                "vote": "VETO" if two_phase.get("veto_by") == "Antagonist" else "CHALLENGE",
                "reason": str((decision.get("antagonist_view") or {}).get("reason") or two_phase.get("reason") or "searched for failure mode")[:160],
            },
            {
                "role": "Auditor",
                "vote": "PASS" if decision.get("status") == "EXECUTING" else "WAIT",
                "reason": decision.get("wait_reason") or decision.get("logic") or "contract checked",
            },
        ]

        logger.info(
            "🏛️ Council verdict: %s %s %s conf=%.3f score=%s reason=%s",
            decision.get("decision_state"),
            decision.get("status"),
            decision.get("ticker"),
            float(decision.get("confidence", 0.0) or 0.0),
            decision.get("decision_score"),
            decision.get("wait_reason") or decision.get("logic", ""),
        )
        try:
            self._save_directive(decision)
            log_council_decision(decision)
        except Exception as journal_err:
            logger.debug(f"Council structured journal skipped: {journal_err}")
        if "evaluation" in locals() and isinstance(evaluation, dict):
            decision["autonomous_director_stats"] = evaluation.get("cycle_stats")

        self._log_decision(decision)
        return decision

    def _log_decision(self, decision: Dict):
        try:
            with open(self.decision_log, "a") as f:
                f.write(json.dumps(decision) + "\n")
            max_mb = float(os.getenv("KIBOT_COUNCIL_DECISION_LOG_MAX_MB", "32") or 32)
            if self.decision_log.stat().st_size > max_mb * 1024 * 1024:
                lines = self.decision_log.read_text(encoding="utf-8", errors="ignore").splitlines()[-5000:]
                self.decision_log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to log decision: {e}")

    def _save_directive(self, directive: Dict):
        try:
            with open(self.directive_log, "w") as f:
                json.dump(directive, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save directive: {e}")

    async def deliberate(self, issue_context: Dict) -> Dict:
        """Centralized deliberation entry point."""
        if issue_context.get("type") == "PROACTIVE_ORACLE":
             return await self.run_strategic_planning(issue_context.get("snapshot", {}))
        return await self.deliberate_system(issue_context)

    # ──────────────────────────────────────────────────────────────────────
    # §13.1 Fast Council — 4 roles, quick filter, deterministic-first
    # ──────────────────────────────────────────────────────────────────────

    async def fast_council(
        self,
        signal: Dict,
        daily_context: Dict,
        capital_state: Optional[Dict] = None,
    ) -> Dict:
        """
        Fast Council (§13.1 — Pre-filter before Deep Council).
        Roles: Hunter, Risk Officer, Liquidity Engineer (det.), Deadline Keeper (det.)

        Returns:
          {"pass": bool, "reason": str, "veto_by": str|None, "fast_confidence": float}

        Only signals that PASS fast council proceed to deep_council().
        """
        pair    = signal.get("symbol", "UNKNOWN")
        lifecycle = signal.get("lifecycle", "IGNITION")
        trade_grade = signal.get("trade_grade", "C")
        confidence  = float(signal.get("confidence", 0.0))
        spread_pct  = float(signal.get("spread_pct") or 0.0)
        obi         = float(signal.get("obi", 0.0))
        tick_pct    = float(signal.get("tick_size_pct", 0.0))
        levels      = int(signal.get("price_levels_24h", 0) or 0)

        daily_color  = daily_context.get("daily_color", "FLAT")
        urgency      = daily_context.get("urgency_level", "LOW")
        deadline_mode = daily_context.get("deadline_mode", "PATIENT")
        risk_mode    = daily_context.get("allowed_risk_mode", "NORMAL")
        quality_req  = daily_context.get("required_trade_quality", "NORMAL")

        # ── Deterministic gate: Liquidity Engineer (§13.3) ──
        if lifecycle in ("TRAP", "LOCAL_TRAP"):
            return {"pass": False, "reason": "TRAP lifecycle rejected", "veto_by": "LiquidityEngineer", "fast_confidence": 0.0}
        if spread_pct > 1.20:
            return {"pass": False, "reason": f"Spread {spread_pct:.2f}% > 1.20% — unsellable", "veto_by": "LiquidityEngineer", "fast_confidence": 0.0}
        if tick_pct > 3.0 or levels < 8:
            return {"pass": False, "reason": f"Tick trap: tick={tick_pct:.2f}%, levels={levels}", "veto_by": "LiquidityEngineer", "fast_confidence": 0.0}

        # [NEW V3.3] Liquidity Score Check (Generalized Intelligence)
        if signal.get("liquidity_score", 1.0) < 0.25:
            return {"pass": False, "reason": "Critically low liquidity score", "veto_by": "LiquidityEngineer", "fast_confidence": 0.0}

        market_quality = signal.get("market_quality", {})
        if isinstance(market_quality, dict) and market_quality.get("ok") is False:
            return {"pass": False, "reason": f"Market quality: {market_quality.get('reason')}", "veto_by": "LiquidityEngineer", "fast_confidence": 0.0}

        # ── Deterministic gate: Deadline Keeper (§13.4) ──
        if risk_mode == "WAIT":
            return {"pass": False, "reason": f"risk_mode=WAIT — daily context prohibits new entries", "veto_by": "DeadlineKeeper", "fast_confidence": 0.0}

        # [REFINED V3.3] Organized Greed Quality Gate (§11.2)
        if daily_color == "GREEN":
            # Proteksi profit: Hanya Grade A/A+ yang boleh lewat
            if trade_grade not in ("A", "A+"):
                return {"pass": False, "reason": f"LOCK_GREEN: Grade {trade_grade} rejected (A/A+ required)", "veto_by": "DeadlineKeeper", "fast_confidence": 0.0}
            if confidence < 0.85:
                 return {"pass": False, "reason": f"LOCK_GREEN: Confidence {confidence:.2f} below protection floor 0.85", "veto_by": "DeadlineKeeper", "fast_confidence": 0.0}

        if deadline_mode == "LOCK_GREEN" and trade_grade not in ("A", "A+"):
            return {"pass": False, "reason": "LOCK_GREEN: only grade A/A+ allowed", "veto_by": "DeadlineKeeper", "fast_confidence": 0.0}
        if quality_req == "EXCEPTIONAL" and trade_grade not in ("A", "A+"):
            return {"pass": False, "reason": f"EXCEPTIONAL quality required, got {trade_grade}", "veto_by": "DeadlineKeeper", "fast_confidence": 0.0}
        if quality_req == "HIGH" and trade_grade not in ("A", "A+", "B"):
            return {"pass": False, "reason": f"HIGH quality required, got {trade_grade}", "veto_by": "DeadlineKeeper", "fast_confidence": 0.0}
        if lifecycle == "DISTRIBUTION":
            return {"pass": False, "reason": "DISTRIBUTION lifecycle: anti-top rule", "veto_by": "DeadlineKeeper", "fast_confidence": 0.0}

        # ── AI gate: Hunter + Risk Officer (§13.1, §13.2) ──
        # Fast AI deliberation — qwen2.5:1.5b speed
        ai_payload = {
            "signal_summary": {
                "pair":         pair,
                "lifecycle":    lifecycle,
                "trade_grade":  trade_grade,
                "confidence":   confidence,
                "obi":          obi,
                "spread_pct":   spread_pct,
            },
            "daily_context": {
                "color":        daily_color,
                "urgency":      urgency,
                "deadline_mode": deadline_mode,
                "minutes":      daily_context.get("minutes_to_midnight", 480),
            },
            "question": (
                "Is this signal worth sending to Deep Council? "
                "Reply: PASS or REJECT with one-line reason."
            ),
        }
        hunter_result  = await self._query_ai_guarded("fast_hunter", ai_payload, timeout=8.0)
        risk_result    = await self._query_ai_guarded("fast_risk_officer", ai_payload, timeout=8.0)

        # Parse AI results conservatively
        def _ai_says_pass(result: dict) -> bool:
            if result.get("is_fallback"):
                return confidence >= 0.65  # fallback: trust scanner confidence
            text = str(result.get("decision", result.get("action", result.get("response", "")))).upper()
            return "PASS" in text or "BUY" in text or "ENTER" in text

        hunter_pass = _ai_says_pass(hunter_result)
        risk_pass   = _ai_says_pass(risk_result)

        if not hunter_pass and not risk_result.get("is_fallback"):
            return {
                "pass":             False,
                "reason":           f"Hunter rejected: {hunter_result.get('reason', 'weak signal')}",
                "veto_by":          "Hunter",
                "fast_confidence":  round(confidence * 0.8, 4),
            }
        if not risk_pass and not risk_result.get("is_fallback"):
            return {
                "pass":             False,
                "reason":           f"RiskOfficer rejected: {risk_result.get('reason', 'risk too high')}",
                "veto_by":          "RiskOfficer",
                "fast_confidence":  round(confidence * 0.85, 4),
            }

        return {
            "pass":             True,
            "reason":           "Passed fast council (Liquidity, Deadline, Hunter, Risk)",
            "veto_by":          None,
            "fast_confidence":  round(confidence, 4),
        }

    # ──────────────────────────────────────────────────────────────────────
    # §13.2 Deep Council — 6 roles, full deliberation before buy mandate
    # ──────────────────────────────────────────────────────────────────────

    async def deep_council(
        self,
        signal: Dict,
        daily_context: Dict,
        exit_plan: Optional[Dict] = None,
        pair_memory: Optional[Dict] = None,
        capital_state: Optional[Dict] = None,
    ) -> Dict:
        """
        Deep Council (§13.2 — Final gate before real money order).
        Roles: Exit Planner, Antagonist, Historian, Regime Analyst, Allocator, Auditor/Judge

        Returns:
          {
            "decision_state": "ENTER|WAIT|EXIT",
            "deadline_mode":  str,
            "confidence":     float,
            "breakdown":      dict,   # §16.8
            "trade_grade":    str,    # §16.9
            "reason":         str,
            "veto_by":        str|None,
            "budget_fraction": float,
          }
        """
        pair        = signal.get("symbol", "UNKNOWN")
        lifecycle   = signal.get("lifecycle", "IGNITION")
        trade_grade = signal.get("trade_grade", "C")
        confidence  = float(signal.get("confidence", 0.0))
        historian_verdict = (pair_memory or {}).get("verdict", signal.get("historian_profile", {}).get("verdict", "UNKNOWN"))

        daily_color   = daily_context.get("daily_color", "FLAT")
        urgency       = daily_context.get("urgency_level", "LOW")
        deadline_mode = daily_context.get("deadline_mode", "PATIENT")
        minutes       = daily_context.get("minutes_to_midnight", 480)

        # ── Auditor/Judge hard rules (§13.5 — vetoes rule violations) ──
        if trade_grade == "F":
            return self._deep_reject("Auditor", "F-grade signal — hard reject by Auditor", deadline_mode, confidence, trade_grade)
        if historian_verdict == "DEAD":
            return self._deep_reject("Historian", "Pair verdict DEAD — Historian blocks", deadline_mode, confidence, trade_grade)

        # ── Antagonist — raises trap concern (deepseek-r1:7b if available) ──
        antagonist_payload = {
            "signal": {
                "pair":               pair,
                "lifecycle":          lifecycle,
                "confidence":         confidence,
                "trade_grade":        trade_grade,
                "historian_verdict":  historian_verdict,
                "confidence_breakdown": signal.get("confidence_breakdown", {}),
                "exit_quality":       signal.get("exit_quality", "C"),
            },
            "daily_context":   daily_context,
            "exit_plan":       exit_plan or {},
            "question":        "Find the strongest reason this trade could fail or trap KiBot. Reply: SAFE or RISKY with explanation.",
        }
        antagonist = await self._query_ai_guarded("antagonist", antagonist_payload, timeout=15.0)

        # [REFINED V3.3] Strict Deterministic Antagonist (Trap Simulation)
        antagonist_text = str(antagonist.get("decision", antagonist.get("response", ""))).upper()

        # Veto if AI detects RISKY AND historian has ever flagged this as TRAP_PRONE
        if "RISKY" in antagonist_text and historian_verdict == "TRAP_PRONE":
            return self._deep_reject("Antagonist", f"Antagonist+Historian veto: TRAP_PRONE pair rejected", deadline_mode, confidence, trade_grade)

        # Veto if AI detects RISKY AND we are in GREEN state (Organized Greed protection)
        if "RISKY" in antagonist_text and daily_color == "GREEN":
            return self._deep_reject("Antagonist", "Antagonist Veto: RISKY detected in GREEN state (Protect Profit)", deadline_mode, confidence, trade_grade)

        # Fallback Antagonist logic: If spread is widening or OBI is dropping, it's a trap
        if float(signal.get("spread_pct", 0)) > 0.85 and float(signal.get("obi", 0)) < -0.30:
            return self._deep_reject("Antagonist", "Deterministic Trap Veto: Widening spread + Negative OBI", deadline_mode, confidence, trade_grade)

        # ── Exit Planner — check exit plan quality (deterministic) ──
        exit_verdict = "EXIT_OK"
        if exit_plan:
            hard_stop = float(exit_plan.get("hard_stop_pct", 2.5))
            max_hold  = int(exit_plan.get("max_hold_minutes", 120))
            if max_hold < 10:
                return self._deep_reject("ExitPlanner", f"Exit plan: max_hold={max_hold}m is dangerously short", deadline_mode, confidence, trade_grade)
            if hard_stop > 5.0:
                return self._deep_reject("ExitPlanner", f"Hard stop {hard_stop}% is too wide for capital protection", deadline_mode, confidence, trade_grade)
            exit_verdict = exit_plan.get("distribution_exit_rules", {}).get("exit_if_obi_below", "ok")

        # ── Regime Analyst + Historian — AI deliberation ──
        regime_payload = {
            "signal":         {"pair": pair, "lifecycle": lifecycle, "confidence": confidence},
            "daily_context":  daily_context,
            "pair_memory":    pair_memory or {},
            "question":       "Does market regime and pair history support this entry? Reply: SUPPORT or OPPOSE.",
        }
        regime_result   = await self._query_ai_guarded("regime_analyst", regime_payload, timeout=12.0)
        historian_result = await self._query_ai_guarded("historian", regime_payload, timeout=10.0)

        def _supports(r: dict) -> bool:
            if r.get("is_fallback"):
                return True  # fallback = neutral, let through
            t = str(r.get("decision", r.get("response", ""))).upper()
            return "SUPPORT" in t or "PASS" in t or "BUY" in t or "ENTER" in t

        regime_ok    = _supports(regime_result)
        historian_ok = _supports(historian_result)

        # Need at least one positive vote from regime/historian
        if not regime_ok and not historian_ok:
            return self._deep_reject(
                "RegimeAnalyst+Historian",
                "Both Regime Analyst and Historian oppose entry",
                deadline_mode, confidence, trade_grade,
            )

        # ── Allocator — determine budget_fraction (deterministic) ──
        cap_state = (capital_state or {}).get("capital_state", "NORMAL")
        sizing_mode = (capital_state or {}).get("sizing_mode", "NORMAL")
        budget_fraction_map = {
            "MICRO":   0.90,
            "SMALL":   0.35,
            "NORMAL":  0.20,
            "LARGE":   0.10,
        }
        budget_fraction = budget_fraction_map.get(cap_state, 0.20)
        if sizing_mode == "PROBE":
            budget_fraction = min(budget_fraction, 0.25)
        elif sizing_mode in ("REDUCED", "PROTECT"):
            budget_fraction = min(budget_fraction, 0.10)

        # Reduce if GREEN + urgency
        if daily_color == "GREEN" and urgency in ("HIGH", "CRITICAL"):
            budget_fraction *= 0.5
        budget_fraction = round(min(0.95, max(0.05, budget_fraction)), 3)

        # ── Build §16.8 confidence breakdown ──
        breakdown = signal.get("confidence_breakdown", {})
        if "antagonist_penalty" not in breakdown:
            breakdown["antagonist_penalty"] = -0.05 if "RISKY" in antagonist_text else 0.0
        if not regime_ok:
            breakdown["regime_penalty"] = -0.04
        if not historian_ok:
            breakdown["historian_penalty"] = -0.03

        final_confidence = round(min(0.98, max(0.0, confidence + sum(
            v for v in breakdown.values() if isinstance(v, (int, float)) and v < 0
        ))), 4)

        return {
            "decision_state":   "ENTER",
            "deadline_mode":    deadline_mode,
            "confidence":       final_confidence,
            "breakdown":        breakdown,
            "trade_grade":      trade_grade,
            "reason":           (
                f"Deep Council passed: lifecycle={lifecycle}, grade={trade_grade}, "
                f"historian={historian_verdict}, regime={'ok' if regime_ok else 'neutral'}"
            ),
            "veto_by":          None,
            "budget_fraction":  budget_fraction,
            "sizing_mode":      sizing_mode,
            "capital_state":    cap_state,
        }

    @staticmethod
    def _deep_reject(role: str, reason: str, deadline_mode: str, confidence: float, trade_grade: str) -> Dict:
        """Helper: build a standardized deep council REJECT response."""
        return {
            "decision_state":  "WAIT",
            "deadline_mode":   deadline_mode,
            "confidence":      round(confidence * 0.5, 4),  # downgrade
            "breakdown":       {},
            "trade_grade":     trade_grade,
            "reason":          reason,
            "veto_by":         role,
            "budget_fraction": 0.0,
        }

    async def council_mandate(
        self,
        signal: Dict,
        daily_context: Dict,
        capital_state: Optional[Dict] = None,
        exit_plan: Optional[Dict] = None,
        pair_memory: Optional[Dict] = None,
    ) -> Dict:
        """
        Full two-phase council pipeline per §13:
        1. fast_council() — eliminates obvious rejects quickly
        2. deep_council() — full deliberation for survivors

        Returns final mandate dict with decision_state, trade_grade, confidence, etc.
        """
        # Phase 1: Fast filter
        fast = await self.fast_council(signal, daily_context, capital_state)
        if not fast.get("pass"):
            logger.info(
                f"[FastCouncil] REJECT {signal.get('symbol')} — "
                f"veto={fast.get('veto_by')} reason={fast.get('reason')}"
            )
            return {
                "decision_state":  "WAIT",
                "deadline_mode":   daily_context.get("deadline_mode", "PATIENT"),
                "confidence":      fast.get("fast_confidence", 0.0),
                "breakdown":       {},
                "trade_grade":     signal.get("trade_grade", "F"),
                "reason":          fast.get("reason", "rejected by fast council"),
                "veto_by":         fast.get("veto_by"),
                "budget_fraction": 0.0,
                "phase":           "FAST_COUNCIL",
            }

        # Phase 2: Deep deliberation
        deep = await self.deep_council(
            signal, daily_context, exit_plan, pair_memory, capital_state
        )
        deep["phase"] = "DEEP_COUNCIL"
        if deep["decision_state"] == "ENTER":
            logger.info(
                f"[DeepCouncil] MANDATE {signal.get('symbol')} | "
                f"conf={deep['confidence']:.3f} | grade={deep['trade_grade']} | "
                f"budget={deep['budget_fraction']:.1%}"
            )
        else:
            logger.info(
                f"[DeepCouncil] REJECT {signal.get('symbol')} — "
                f"veto={deep.get('veto_by')} reason={deep.get('reason')}"
            )
        return deep

    async def run_background_ai_review(self, signals_context: Dict[str, Any], decision: Dict[str, Any]) -> None:
        """
        Asynchronously runs COUNCIL_ANTAGONIST and COUNCIL_SPEAKER to construct
        and persist an out-of-band strategy audit file `state/ai_strategy_review.json`.
        Does NOT block or influence the hot-path decision thread.
        """
        try:
            logger.info("🤖 Starting out-of-band AI Council deliberation review task...")
            
            # Query Antagonist View in background
            antagonist_view = await self._query_ai_guarded("COUNCIL_ANTAGONIST", {
                **signals_context,
                "current_strategy": load_strategy(),
                "is_midnight_approaching": signals_context.get("is_midnight_approaching", False),
            }, timeout=float(os.getenv("KIBOT_COUNCIL_ANTAGONIST_TIMEOUT_SEC", "14") or 14))

            # Query Speaker verdict / summary review
            speaker_view = await self._query_ai_guarded("COUNCIL_SPEAKER", {
                **signals_context,
                "antagonist_view": antagonist_view,
                "is_midnight_approaching": signals_context.get("is_midnight_approaching", False)
            }, timeout=float(os.getenv("KIBOT_COUNCIL_SPEAKER_TIMEOUT_SEC", "18") or 18))

            # Formulate the audit block
            review_payload = {
                "timestamp": time.time(),
                "datetime": time.strftime("%Y-%m-%d %H:%M:%S WIB", time.localtime()),
                "status": "COMPLETED",
                "hot_path_decision": {
                    "action": decision.get("action"),
                    "ticker": decision.get("ticker"),
                    "confidence": decision.get("confidence")
                },
                "ai_review": {
                    "antagonist_view": antagonist_view,
                    "speaker_view": speaker_view
                },
                "proposed_adjustments": {
                    "confidence_floor_delta": -0.02 if str(speaker_view.get("verdict") or "").upper() == "BULLISH" else 0.01,
                    "reasoning": str(speaker_view.get("reason") or "Neutral outlook")
                }
            }

            review_file = self.state_dir / "ai_strategy_review.json"
            review_file.write_text(json.dumps(review_payload, indent=2), encoding="utf-8")
            logger.info(f"💾 Asynchronous AI review saved successfully at {review_file}")

        except Exception as e:
            logger.error(f"❌ Error in asynchronous AI Strategy Review: {e}")
