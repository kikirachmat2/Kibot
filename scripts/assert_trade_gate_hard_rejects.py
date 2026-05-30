#!/usr/bin/env python3
from __future__ import annotations

from Core.Intelligence.expected_value import ev_from_candidate
from Core.Intelligence.strategy_scorecard import score_candidate
from Core.Decision.deterministic_decision_gate import evaluate_live_trade


def main() -> int:
    ev = ev_from_candidate({"historical_sample_size": 1})
    if ev.approved:
        print("BLOCKED:EV")
        return 1
    score = score_candidate(
        signal_quality_dict={"grade": "STRONG"},
        ev_analysis_dict={"approved": False, "ev_pct": 0.5},
        market_regime="BULL",
    )
    if score.verdict.value == "APPROVED":
        print("BLOCKED:SCORECARD")
        return 1
    gate = evaluate_live_trade(
        {
            "ev_analysis": {"approved": False, "ev_pct": 0.5},
            "pretrade_simulation": {"simulation_verdict": "REJECT"},
            "historical_sample_size": 0,
            "spread_pct": 2.0,
            "slippage_est_pct": 2.0,
        },
        runtime_state={"risk_state": "OK"},
    )
    if gate.approved:
        print("BLOCKED:DETERMINISTIC_GATE")
        return 1
    print("OK:HARD_REJECTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

