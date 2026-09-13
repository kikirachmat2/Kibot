from __future__ import annotations

from Core.Decision.decision_authority import DecisionAuthority
from Core.Decision.deadline_profit_enforcer import DeadlineProfitEnforcer
from Core.Intelligence.daily_context import _required_trade_quality


def test_recovery_quality_allows_normal_floor_for_low_urgency():
    assert _required_trade_quality("RECOVERY", "LOW") == "NORMAL"
    assert _required_trade_quality("RECOVERY", "NORMAL") == "NORMAL"
    assert _required_trade_quality("RECOVERY", "HIGH") == "HIGH"
    assert _required_trade_quality("RECOVERY", "CRITICAL") == "EXCEPTIONAL"


def test_deadline_enforcer_marks_recovery_as_cautious_entry(tmp_path):
    enforcer = DeadlineProfitEnforcer(state_dir=tmp_path)
    state = enforcer.evaluate_enforcer(daily_pnl_pct=-1.25, daily_pnl_idr=-250_000, minutes_to_midnight=360)

    assert state["stage"] == "RECOVERY"
    assert state["locked_for_day"] is False
    assert state["required_action"] == "ENTER_CAUTIOUSLY"


def test_decision_authority_recovery_mode_still_enters(tmp_path):
    authority = DecisionAuthority(state_dir=tmp_path)
    decision = authority.evaluate(
        {
            "signals": [
                {
                    "symbol": "EDEN/IDR",
                    "ticker": "EDEN/IDR",
                    "confidence": 0.64,
                    "opportunity_score": 0.54,
                    "spread_pct": 0.18,
                    "lifecycle": "IGNITION",
                    "liquidity_score": 0.82,
                }
            ],
            "evidence_bundle": {"risk_penalty": 0.20},
            "whatif_snapshot": {"results": {"EDEN": {"expectedValue": 0.03}}},
            "today_trade_activity": {"entries": 0},
            "daily_context": {"daily_color": "RECOVERY", "urgency_level": "LOW"},
            "minutes_to_midnight": 360,
        }
    )

    assert decision["status"] == "EXECUTING"
    assert decision["action"] == "BUY"
    assert decision["ticker"] == "EDEN/IDR"
    assert decision["trade_profile"] == "RECOVERY"
