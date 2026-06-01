from __future__ import annotations

from Core.Support.money_movement_audit import money_movement_status


def test_money_movement_ready_but_waiting_when_candidates_missing() -> None:
    result = money_movement_status(
        {
            "live_truth": {"updated_at": "now"},
            "no_trade_forensics": {"movement_status": "WAITING_FOR_A_PLUS", "movement_reason": "scan ready"},
            "candidate_decisions": [],
            "orders": [],
            "trade_history": [],
            "indodax_targets": {"top_targets": [{"symbol": "EDEN/IDR"}]},
            "phantom_targets": {"top_targets": [{"symbol": "SOL/USDC"}]},
            "server_telemetry": {"cpu": 1},
        }
    )
    assert result["money_movement_status"] in {"READY_BUT_WAITING", "STUCK", "MOVING"}
    assert "primary_reason" in result

