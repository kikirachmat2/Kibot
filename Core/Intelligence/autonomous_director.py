"""Autonomous Director — brain orchestrator that ties all intelligence layers together.

Execution pipeline per cycle:
  1. Receive candidate list from scanner
  2. Gate each candidate through SignalQuality
  3. Run ExpectedValue computation
  4. Check PunishmentEngine quarantine
  5. Run StrategyScorecard
  6. Output final ranked list with verdicts

The Director never places orders directly. It only annotates candidates
with verdicts and recommended position sizes, then hands off to the Executor.

Live trading gate:
  Candidates with APPROVED verdict only reach the Executor when:
    KIBOT_LIVE_TRADING_ENABLED=true  and the live gate is open.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

from .signal_quality import batch_evaluate as sq_batch
from .expected_value import batch_evaluate_ev
from .strategy_scorecard import run_scorecard, ScorecardVerdict
from .punishment_engine import get_engine as get_punishment_engine
from .no_idle_director import NoIdleDirector

log = logging.getLogger(__name__)

_LIVE_ENABLED = os.getenv("KIBOT_LIVE_TRADING_ENABLED", "false").lower() == "true"

# Maximum candidates forwarded to executor per cycle
MAX_APPROVED_PER_CYCLE = 3


class AutonomousDirector:
    """Stateless-per-call orchestrator — call `evaluate_cycle()` each scanner tick."""

    def __init__(self, market_regime: str = "UNKNOWN") -> None:
        self.market_regime = market_regime
        self._punishment = get_punishment_engine()
        self._no_idle = NoIdleDirector()

    def update_regime(self, regime: str) -> None:
        self.market_regime = regime.upper()

    def evaluate_cycle(
        self,
        raw_candidates: List[Dict[str, Any]],
        *,
        market_regime: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Full evaluation pipeline for one scanner cycle.

        Returns a summary dict with approved, shadow, rejected lists
        and a cycle_stats block.
        """
        regime = (market_regime or self.market_regime).upper()
        start = time.time()

        if not raw_candidates:
            return self._empty_result(regime, start)

        # Step 1 — Signal Quality gate
        candidates = sq_batch(raw_candidates)

        # Step 1.5 — Inject Historical Strategy Statistics
        try:
            from .strategy_stats import get_stats_aggregator
            aggregator = get_stats_aggregator()
            for c in candidates:
                aggregator.inject_stats(c)
        except Exception as err:
            pass

        # Step 2 — Expected Value gate
        candidates = batch_evaluate_ev(candidates)

        # Step 3 — Punishment status injection
        for c in candidates:
            sid = c.get("strategy_id") or c.get("symbol") or "default"
            c["quarantine_active"] = self._punishment.is_quarantined(sid)
            c["punishment_severity"] = self._punishment.get_severity(sid)

        # Step 4 — Strategy Scorecard
        for c in candidates:
            run_scorecard(c, market_regime=regime)

        # Step 5 — Sort and partition
        candidates.sort(
            key=lambda c: c.get("scorecard", {}).get("composite_score", 0.0),
            reverse=True,
        )

        approved: List[Dict[str, Any]] = []
        shadow: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []

        for c in candidates:
            verdict = c.get("scorecard_verdict", "REJECTED")
            if verdict == ScorecardVerdict.APPROVED.value:
                approved.append(c)
            elif verdict == ScorecardVerdict.PAPER_ONLY.value:
                shadow.append(c)
            else:
                rejected.append(c)

        # Step 6 — Apply live gate
        live_forward: List[Dict[str, Any]] = []
        if _LIVE_ENABLED:
            live_forward = approved[:MAX_APPROVED_PER_CYCLE]
            log.info(
                "[Director] LIVE gate active — forwarding %d approved candidates to Executor",
                len(live_forward),
            )
        elif approved:
            log.info(
                "[Director] %d candidates APPROVED but live gate OFF — shadow mode",
                len(approved),
            )

        elapsed_ms = round((time.time() - start) * 1000, 1)
        best_route = "indodax" if approved else ("scanning" if rejected else "wait")
        self._no_idle.update(
            best_route_now=best_route,
            best_candidate_now=approved[0] if approved else (rejected[0] if rejected else {}),
            why_not_trading="no candidate approved" if not approved else "",
            next_action="SCAN" if not approved else "ENTER",
            routes_checked_this_cycle=["indodax"],
            approved_candidates=len(approved),
            rejected_candidates=len(rejected),
            posture="ENTERING" if approved else "ACTIVE_SEARCHING",
            next_check_seconds=10,
        )
        return {
            "approved": approved,
            "shadow": shadow,
            "rejected": rejected,
            "live_forward": live_forward,
            "cycle_stats": {
                "total_evaluated": len(candidates),
                "approved_count": len(approved),
                "shadow_count": len(shadow),
                "rejected_count": len(rejected),
                "live_forward_count": len(live_forward),
                "market_regime": regime,
                "live_trading_enabled": _LIVE_ENABLED,
                "live_gate_open": bool(_LIVE_ENABLED),
                "elapsed_ms": elapsed_ms,
                "evaluated_at": start,
            },
        }

    def record_outcome(self, strategy_id: str, pnl_pct: float) -> None:
        """Feed trade outcomes back into the punishment engine."""
        self._punishment.record_trade(strategy_id, pnl_pct)

    @staticmethod
    def _empty_result(regime: str, start: float) -> Dict[str, Any]:
        return {
            "approved": [],
            "shadow": [],
            "rejected": [],
            "live_forward": [],
            "cycle_stats": {
                "total_evaluated": 0,
                "approved_count": 0,
                "shadow_count": 0,
                "rejected_count": 0,
                "live_forward_count": 0,
                "market_regime": regime,
                "live_trading_enabled": _LIVE_ENABLED,
                "live_gate_open": bool(_LIVE_ENABLED),
                "elapsed_ms": round((time.time() - start) * 1000, 1),
                "evaluated_at": start,
            },
        }
