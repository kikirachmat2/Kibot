from __future__ import annotations

from fastapi.testclient import TestClient

from Core.Intelligence.kibot_dashboard import app


def test_dashboard_v6_payload_top_level_keys():
    client = TestClient(app)
    payload = client.get("/api/control-plane").json()
    for key in (
        "runtime",
        "portfolio_v6",
        "decision",
        "venues",
        "workflow",
        "opportunity_funnel",
        "ai_system",
        "orders",
        "logs",
        "debug",
    ):
        assert key in payload
    assert payload["runtime"]["mode"] == "LIVE_ONLY"
    assert "current_action" in payload["decision"]
    assert payload["portfolio_v6"]["total_equity_idr"] is not None
