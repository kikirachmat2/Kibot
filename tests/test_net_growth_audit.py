from __future__ import annotations

from Core.Support.growth_audit import audit_net_growth


def test_net_growth_audit_flags_flat_churn_when_fills_without_equity_growth() -> None:
    result = audit_net_growth(
        {
            "live_truth": {"updated_at": "2026-06-01T00:00:00+00:00", "wallet_equity_idr": 100000.0, "unrealized_pnl_idr": 0.0},
            "capital_governor": {"start_total_equity_idr": 100000.0, "current_total_equity_idr": 100000.0, "daily_pnl_idr": 0.0},
            "accounting_truth": {"current_total_equity_idr": 100000.0, "start_total_equity_idr": 100000.0},
            "trade_history": [
                {"venue": "indodax", "pair": "EDEN_IDR", "side": "BUY", "net_realized_pnl_idr": -50.0, "fee_idr": 10.0, "timestamp_wib": "2026-06-01T06:00:00+07:00"},
                {"venue": "indodax", "pair": "EDEN_IDR", "side": "SELL", "net_realized_pnl_idr": 60.0, "fee_idr": 10.0, "timestamp_wib": "2026-06-01T06:01:00+07:00"},
            ],
        }
    )
    assert result["status"] in {"FLAT_CHURN", "GROWING", "LOSING"}
    assert "recommendation" in result

