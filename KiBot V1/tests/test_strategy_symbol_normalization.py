from __future__ import annotations

from Core.Support.growth_audit import audit_strategy_symbol_normalization


def test_strategy_symbol_normalization_merges_eden_aliases() -> None:
    result = audit_strategy_symbol_normalization(
        {
            "trade_history": [
                {"pair": "EDEN_IDR", "net_realized_pnl_idr": 100.0, "source": "indodax"},
                {"pair": "EDEN/IDR", "net_realized_pnl_idr": -10.0, "source": "unknown"},
            ]
        }
    )
    assert result["eden"]["count"] == 2
    assert "EDEN_IDR" in result["canonical_map"]

