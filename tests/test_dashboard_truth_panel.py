from fastapi.testclient import TestClient

from Core.Intelligence.kibot_dashboard import app


def test_dashboard_control_plane_exposes_truth_keys():
    client = TestClient(app)
    payload = client.get("/api/control-plane").json()
    assert "system_truth" in payload
    assert "daily_reset" in payload
    assert "indodax_top_targets" in payload
    assert "phantom_top_targets" in payload
