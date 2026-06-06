from __future__ import annotations

from Core.Support.money_movement_audit import candidate_pipeline_audit


def test_candidate_pipeline_detects_gate_bottleneck() -> None:
    result = candidate_pipeline_audit(
        {
            "candidate_decisions": [{"venue": "indodax", "approved": False, "reason": "EV_SAMPLE_TOO_SMALL"}],
            "orders": [],
            "trade_history": [],
            "indodax_targets": {"top_targets": [{"symbol": "BTC/IDR"}]},
            "server_telemetry": {"cpu": 1},
        }
    )
    assert result["indodax"]["bottleneck"] in {"GATE", "SCANNER", "SIZE", "EXECUTOR", "NONE"}
    assert "indodax" in result
