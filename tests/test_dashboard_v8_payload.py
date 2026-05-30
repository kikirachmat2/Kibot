from fastapi.testclient import TestClient

from Core.Intelligence.kibot_dashboard import app


def test_dashboard_v8_payload():
    payload = TestClient(app).get("/api/control-plane").json()
    for key in ("runtime", "portfolio_v8", "decision", "venues_v8", "workflow_v8", "opportunity_funnel", "ai_system", "orders_v8", "logs_v8", "debug"):
        assert key in payload
    assert payload["runtime"]["mode"] == "LIVE_ONLY"
