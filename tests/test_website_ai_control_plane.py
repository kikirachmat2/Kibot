from fastapi.testclient import TestClient

from Core.Intelligence.kibot_dashboard import app


def test_control_plane_exposes_ai_system():
    client = TestClient(app)
    payload = client.get("/api/control-plane").json()
    assert "ai_system" in payload
    ai = payload["ai_system"]
    assert ai["order_permission"] == "DENIED"
    assert ai["override_permission"] == "DENIED"
    assert ai["role"] == "advisory_only"
    assert ai["inventory_file"] == "state/ai_system_inventory.json"
    assert "live_truth" in payload
    assert payload["live_truth"]["fresh"] in {True, False}
