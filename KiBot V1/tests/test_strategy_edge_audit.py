from __future__ import annotations

from Core.Support.money_movement_audit import strategy_edge_audit


def test_strategy_edge_reports_insufficient_data() -> None:
    result = strategy_edge_audit(
        {
            "trade_history": [
                {"venue": "indodax", "pair": "EDEN/IDR", "net_realized_pnl_idr": 1000},
                {"venue": "indodax", "pair": "EDEN/IDR", "net_realized_pnl_idr": -500},
            ]
        }
    )
    assert result["strategies"]
    assert result["strategies"][0]["status"] == "INSUFFICIENT_DATA"

