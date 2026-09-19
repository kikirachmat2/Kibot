import pytest
from fastapi.testclient import TestClient
from cluster.server_batam import app, CLUSTER_SECRET

client = TestClient(app)

def test_batam_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "HEALTHY"
    assert data["node"] == "BATAM_RESEARCH_NODE"
    assert data["port"] == 5001
    assert "sentiment_analysis" in data["capabilities"]

def test_batam_analyze_sentiment_symbols():
    payload = {"symbols": ["BTC", "ETH"]}
    resp = client.post("/analyze_sentiment", json=payload, headers={"X-Kibot-Secret": CLUSTER_SECRET})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert "BTC" in data["results"]
    assert "ETH" in data["results"]
    assert data["results"]["BTC"]["sentiment_score"] == 0.25

def test_batam_analyze_sentiment_text():
    payload = {"text": "bitcoin pump"}
    resp = client.post("/analyze_sentiment", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert "TEXT_INPUT" in data["results"]
    assert data["results"]["TEXT_INPUT"]["text"] == "bitcoin pump"

def test_batam_optimize_portfolio():
    payload = {"assets": ["BTC", "ETH", "SOL"], "target_risk": 0.12}
    resp = client.post("/optimize_portfolio", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert len(data["weights"]) == 3
    assert abs(sum(data["weights"].values()) - 1.0) < 0.01
    assert data["target_risk"] == 0.12

def test_batam_auth_failure():
    # If host is remote and secret is invalid, should reject with 401
    resp = client.post(
        "/analyze_sentiment",
        json={"symbols": ["BTC"]},
        headers={"X-Kibot-Secret": "invalid_token_123", "X-Forwarded-For": "100.64.0.1"},
    )
    # When testclient sets remote host, client.host is testclient, but invalid secret from non-local rejects
    # Let's test with custom secret directly
    from cluster.server_batam import verify_secret
    from unittest.mock import MagicMock
    from fastapi import HTTPException

    mock_req = MagicMock()
    mock_req.client.host = "213.35.118.26" # Remote host
    with pytest.raises(HTTPException) as exc:
        verify_secret(mock_req, x_kibot_secret="wrong_secret")
    assert exc.value.status_code == 401
