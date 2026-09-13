from __future__ import annotations

from Core.Intelligence import trade_history, order_tracker
from Core.Intelligence.exit_plan import (
    build_exit_plan,
    minimum_profitable_exit_pct,
)


def test_trade_history_prefers_net_pnl_and_shows_fee(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_history, "HISTORY_DIR", tmp_path / "trade_history")

    trade_history.record_trade_event(
        "ORDER_RECONCILED",
        {
            "order_id": "eden_buy_001",
            "pair": "EDEN/IDR",
            "side": "BUY",
            "source": "executor",
            "status": "CLOSED",
            "price_idr": 123.45,
            "amount_coin": 10,
            "amount_idr": 1234.5,
            "fee_idr": 12.5,
            "gross_realized_pnl_idr": 150.0,
            "net_realized_pnl_idr": 137.5,
            "realized_pnl_idr": 137.5,
            "realized_pnl_pct": 11.15,
            "reason": "sell_confirmed",
        },
    )

    summary = trade_history.summarize_today()
    assert summary["sell_fills"] == 1
    assert summary["realized_pnl_idr"] == 137.5
    assert summary["fee_paid_idr"] == 12.5
    assert any("fee Rp 12" in item["message"] for item in summary["recent_activity"])


def test_order_tracker_reconcile_is_fee_aware(tmp_path, monkeypatch):
    monkeypatch.setattr(order_tracker, "ORDERS_DIR", tmp_path / "orders")
    monkeypatch.setattr(order_tracker, "INDEX_FILE", order_tracker.ORDERS_DIR / "_index.json")

    tracker = order_tracker.OrderTracker()
    order_id = tracker.create(
        "EDEN/IDR",
        "BUY",
        10_000,
        100.0,
        mandate={"source": "unit-test", "budget_fraction": 0.1},
        exit_plan={"max_hold_minutes": 15},
        signal={"trade_grade": "A", "confidence": 0.9},
    )
    tracker.transition(order_id, "SUBMITTED", note="sent")
    tracker.transition(order_id, "FILLED", fill_price=100.0, coin_amount=100.0, note="filled")

    record = tracker.reconcile(order_id, sell_value_idr=11_250.0, fee_idr=250.0)
    assert record["pnl_idr"] == 1_000.0


def test_exit_plan_clamps_to_profitable_floor():
    plan = build_exit_plan(
        {"symbol": "EDEN/IDR", "price": 100.0, "lifecycle": "IGNITION", "confidence": 0.6},
        {"daily_color": "FLAT", "urgency_level": "LOW", "deadline_mode": "PATIENT", "minutes_to_midnight": 240},
        "NORMAL",
    )

    assert plan["minimum_profitable_exit_pct"] >= minimum_profitable_exit_pct()
    assert plan["partial_take_profit_pct"] >= plan["minimum_profitable_exit_pct"]
    assert all(threshold >= plan["minimum_profitable_exit_pct"] for threshold, _ in plan["trailing_profit_schedule"])
