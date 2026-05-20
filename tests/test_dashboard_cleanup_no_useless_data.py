from fastapi.testclient import TestClient

from Core.Intelligence.kibot_dashboard import app


def test_dashboard_control_plane_keeps_top_targets_and_truth():
    client = TestClient(app)
    payload = client.get("/api/control-plane").json()
    assert payload.get("system_truth") is not None
    assert "top_targets" in payload


def test_dashboard_portfolio_labels_are_canonical():
    client = TestClient(app)
    html = client.get("/").text
    assert "Total Saldo Gabungan" in html
    assert "Saldo Setelah Reset" in html
    assert "Return Harian" in html
    assert "PnL Harian %" in html
    assert "Saldo Awal Hari Ini" not in html
