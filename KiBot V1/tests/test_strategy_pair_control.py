from __future__ import annotations

from Core.Support.strategy_control_actions import build_strategy_control_actions


def test_strategy_controls_expose_scale_up_guardrails() -> None:
    result = build_strategy_control_actions(
        {
            "strategy_edge_audit": {
                "strategies": [
                    {"strategy": "EDEN/IDR", "status": "NEGATIVE_EDGE", "recommendation": "DISABLE"},
                    {"strategy": "PHA/IDR", "status": "INSUFFICIENT_DATA", "recommendation": "COLLECT_MICRO_PROBE"},
                ]
            }
        }
    )
    assert "EDEN_IDR" in result["disabled_pairs"]
    assert "PHA_IDR" in result["micro_probe_pairs"]
