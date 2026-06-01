from __future__ import annotations

from Core.Support.strategy_control_actions import build_strategy_control_actions


def test_strategy_control_enforces_negative_pairs_and_unknown_source() -> None:
    result = build_strategy_control_actions(
        {
            "strategy_edge_audit": {
                "strategies": [
                    {"strategy": "EDEN/IDR", "status": "NEGATIVE_EDGE", "recommendation": "DISABLE", "venue": "indodax"},
                    {"strategy": "POND/IDR", "status": "INSUFFICIENT_DATA", "recommendation": "COLLECT_MICRO_PROBE", "venue": "phantom"},
                    {"strategy": "XRP/IDR", "status": "POSITIVE_EDGE", "recommendation": "SCALE_UP", "source": "unknown"},
                ]
            }
        }
    )
    assert "EDEN_IDR" in result["disabled_pairs"]
    assert "POND_IDR" in result["micro_probe_pairs"]
    assert "XRP_IDR" in result["do_not_scale_pairs"]
    assert "XRP_IDR" in result["ignored_unknown_source_scaleups"]

