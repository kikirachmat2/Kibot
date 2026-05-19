from fastapi.testclient import TestClient

from Core.Intelligence.kibot_dashboard import app


client = TestClient(app)


def test_control_plane_contains_pumpfun_sections():
    response = client.get("/api/control-plane")
    assert response.status_code == 200
    payload = response.json()
    assert "pumpfun" in payload
    assert "pumpfun" in payload.get("web3", {})
    assert "route_type" in payload["pumpfun"]
    assert "can_buy" in payload["pumpfun"]
    assert "can_sell" in payload["pumpfun"]
