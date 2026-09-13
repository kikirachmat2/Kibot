from __future__ import annotations

from Core.Intelligence import decision_journal, order_tracker, trade_history


def test_trade_history_mirrors_into_decision_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_history, "HISTORY_DIR", tmp_path / "trade_history")
    monkeypatch.setattr(decision_journal, "JOURNAL_DIR", tmp_path / "decision_journal")

    trade_history.record_trade_event(
        "ORDER_FILLED",
        {
            "order_id": "eden_buy_001",
            "pair": "EDEN/IDR",
            "side": "BUY",
            "source": "executor",
            "status": "FILLED",
            "price_idr": 123.45,
            "amount_coin": 10,
            "amount_idr": 1234.5,
        },
    )
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
            "realized_pnl_idr": 250.0,
            "realized_pnl_pct": 20.25,
            "reason": "sell_confirmed",
        },
    )

    trade_summary = trade_history.summarize_today()
    journal_summary = decision_journal.summarize_today()

    assert trade_summary["buy_fills"] == 1
    assert trade_summary["sell_fills"] == 1
    assert trade_summary["realized_pnl_idr"] == 250.0
    assert any(item["tag"] == "BUY" for item in trade_summary["recent_activity"])
    assert any(item["tag"] == "SELL PROFIT" for item in trade_summary["recent_activity"])

    assert journal_summary["trade_events"] == 2
    assert journal_summary["trade_opens"] == 1
    assert journal_summary["trade_closes"] == 1
    assert journal_summary["realized_trade_pnl_idr"] == 250.0
    assert journal_summary["latest_trade_event"]["trade_event_type"] == "ORDER_RECONCILED"


def test_order_tracker_emits_trade_history(tmp_path, monkeypatch):
    monkeypatch.setattr(order_tracker, "ORDERS_DIR", tmp_path / "orders")
    monkeypatch.setattr(order_tracker, "INDEX_FILE", order_tracker.ORDERS_DIR / "_index.json")

    emitted = []

    def fake_emit(event_type, payload):
        emitted.append((event_type, payload))

    monkeypatch.setattr(order_tracker, "_record_trade_event", fake_emit)

    tracker = order_tracker.OrderTracker()
    order_id = tracker.create(
        "EDEN/IDR",
        "BUY",
        10_000,
        123.45,
        mandate={"source": "unit-test", "budget_fraction": 0.1},
        exit_plan={"max_hold_minutes": 15},
        signal={"trade_grade": "A", "confidence": 0.9},
    )
    tracker.transition(order_id, "SUBMITTED", note="sent")
    tracker.transition(order_id, "FILLED", fill_price=123.45, coin_amount=80.86, note="filled")
    tracker.reconcile(order_id, sell_value_idr=11_250)

    event_types = [item[0] for item in emitted]
    assert "ORDER_CREATED" in event_types
    assert "ORDER_SUBMITTED" in event_types
    assert "ORDER_FILLED" in event_types
    assert "ORDER_RECONCILED" in event_types


def test_trade_history_formats_pending_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_history, "HISTORY_DIR", tmp_path / "trade_history")
    monkeypatch.setattr(decision_journal, "JOURNAL_DIR", tmp_path / "decision_journal")

    trade_history.record_trade_event(
        "ENTRY_PENDING",
        {
            "order_id": "eden_pending_001",
            "pair": "EDEN/IDR",
            "side": "BUY",
            "source": "executor",
            "status": "PENDING",
            "price_idr": 123.45,
            "amount_coin": 0.0,
            "amount_idr": 12345.0,
        },
    )
    trade_history.record_trade_event(
        "EXIT_PENDING",
        {
            "order_id": "eden_pending_001",
            "pair": "EDEN/IDR",
            "side": "SELL",
            "source": "executor",
            "status": "PENDING",
            "price_idr": 125.0,
            "amount_coin": 10.0,
            "amount_idr": 1250.0,
        },
    )

    summary = trade_history.summarize_today()
    tags = [item["tag"] for item in summary["recent_activity"]]

    assert "BUY PENDING" in tags
    assert "SELL PENDING" in tags
