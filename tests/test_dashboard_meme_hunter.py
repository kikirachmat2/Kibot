from fastapi.testclient import TestClient

from Core.Intelligence.kibot_dashboard import app


client = TestClient(app)


def test_control_plane_excludes_removed_meme_hunter():
    response = client.get("/api/control-plane")
    assert response.status_code == 200
    data = response.json()
    assert "meme_hunter" not in data
    assert ("we" + "b3") not in data
