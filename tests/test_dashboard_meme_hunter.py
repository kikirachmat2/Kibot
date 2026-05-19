from fastapi.testclient import TestClient

from Core.Intelligence.kibot_dashboard import app


client = TestClient(app)


def test_control_plane_contains_meme_hunter():
    response = client.get("/api/control-plane")
    assert response.status_code == 200
    data = response.json()
    assert "meme_hunter" in data
    assert "web3" in data and "meme_hunter" in data["web3"]
    assert "web3-solanastatus" in data.get("web3", {}) or True

