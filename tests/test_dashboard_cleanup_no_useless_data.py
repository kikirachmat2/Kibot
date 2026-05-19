from fastapi.testclient import TestClient

from Core.Intelligence.kibot_dashboard import app


def test_dashboard_control_plane_keeps_top_targets_and_truth():
    client = TestClient(app)
    payload = client.get("/api/control-plane").json()
    assert payload.get("system_truth") is not None
    assert "top_targets" in payload
