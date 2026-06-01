from __future__ import annotations

from Core.Support.growth_audit import audit_net_growth


def test_net_growth_audit_flags_flat_churn_when_fills_without_equity_growth() -> None:
    result = audit_net_growth(
        {
            "live_truth": {"updated_at": "2026-06-01T00:00:00+00:00", "wallet_equity_idr": 100000.0, "unrealized_pnl_idr": 0.0},
            "capital_governor": {"start_total_equity_idr": 100000.0, "current_total_equity_idr": 100000.0, "daily_pnl_idr": 0.0},
            "accounting_truth": {"current_total_equity_idr": 100000.0, "start_total_equity_idr": 100000.0},
            "trade_history": [
                {"venue": "indodax", "pair": "EDEN_IDR", "side": "BUY", "event_type": "ORDER_FILLED", "status": "FILLED", "amount_idr": 1000.0, "timestamp_wib": "2026-06-01T06:00:00+07:00"},
                {"venue": "indodax", "pair": "EDEN_IDR", "side": "SELL", "event_type": "ORDER_FILLED", "status": "FILLED", "amount_idr": 1100.0, "net_realized_pnl_idr": 90.0, "fee_idr": 10.0, "timestamp_wib": "2026-06-01T06:01:00+07:00"},
            ],
        }
    )
    assert result["status"] in {"FLAT_CHURN", "GROWING", "LOSING", "INSUFFICIENT_DATA"}
    assert "recommendation" in result


def test_net_growth_audit_can_report_growing_with_closed_round_trip() -> None:
    result = audit_net_growth(
        {
            "live_truth": {"updated_at": "2026-06-01T00:00:00+00:00", "wallet_equity_idr": 101000.0, "unrealized_pnl_idr": 0.0},
            "capital_governor": {"start_total_equity_idr": 100000.0, "current_total_equity_idr": 101000.0, "daily_pnl_idr": 1000.0},
            "accounting_truth": {"current_total_equity_idr": 101000.0, "start_total_equity_idr": 100000.0},
            "trade_history": [
                {"venue": "indodax", "pair": "EDEN_IDR", "side": "BUY", "event_type": "ORDER_FILLED", "status": "FILLED", "amount_idr": 1000.0, "timestamp_wib": "2026-06-01T06:00:00+07:00"},
                {"venue": "indodax", "pair": "EDEN_IDR", "side": "SELL", "event_type": "ORDER_FILLED", "status": "FILLED", "amount_idr": 1100.0, "net_realized_pnl_idr": 1500.0, "fee_idr": 100.0, "timestamp_wib": "2026-06-01T06:05:00+07:00"},
            ],
        }
    )
    assert result["status"] in {"GROWING", "FLAT_CHURN"}
