from __future__ import annotations

from Core.Support.growth_audit import audit_fill_quality


def test_fill_quality_counts_duplicates() -> None:
    result = audit_fill_quality(
        {
            "trade_history": [
                {"venue": "indodax", "pair": "EDEN_IDR", "side": "BUY", "status": "FILLED", "fee_idr": 10.0},
                {"venue": "indodax", "pair": "EDEN_IDR", "side": "SELL", "status": "FILLED", "fee_idr": 10.0},
            ]
        }
    )
    assert result["filled_count_24h_reported"] == 2
    assert result["status"] in {"CLEAN", "DUPLICATE_COUNTING", "CHURN", "INCOMPLETE_ACCOUNTING"}

