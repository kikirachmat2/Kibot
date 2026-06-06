from Core.Intelligence.kibot_dashboard import _build_events


def test_dashboard_activity_feed_prefers_trade_history_events():
    summary = {
        "trade_history": {
            "recent_activity": [
                {"tag": "BUY", "message": "EDEN/IDR @ Rp 123 x 10", "agent": "Trade"},
                {"tag": "BUY PENDING", "message": "EDEN/IDR pending buy Rp 10.000 @ Rp 123", "agent": "Trade"},
                {"tag": "SELL LOSS", "message": "EDEN/IDR Rp 250 (-2.00%)", "agent": "Trade"},
            ]
        },
        "order_tracker": {
            "today_summary": {
                "realized_pnl_idr": 999999,
                "realized_pnl_pct": 88.8,
            }
        },
        "council": {"decision_state": "WAIT", "confidence": 0.5},
        "mode": {"live_trading_enabled": True},
        "portfolio": {
            "combined_equity_idr": 1000,
            "realized_pnl_idr": 10,
            "unrealized_pnl_idr": 5,
        },
        "system": {"cpu": 1.0, "ram": 2.0, "disk": 3.0},
        "services": {"kibot-scanner": "active", "kibot-executor": "active"},
    }

    events = _build_events(summary, limit=10)
    tags = [event["tag"] for event in events]

    assert tags.count("BUY") == 1
    assert tags.count("BUY PENDING") == 1
    assert tags.count("SELL LOSS") == 1
    assert tags.count("SELL PROFIT") == 0
    assert "SYSTEM EVENT" not in tags
    assert tags.count("COUNCIL REPORT") == 1
