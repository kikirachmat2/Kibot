import pytest
from fastapi.testclient import TestClient
from cluster.server_batam import app, CLUSTER_SECRET

client = TestClient(app)

def test_batam_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "HEALTHY"
    assert data["node"] == "BATAM_RESEARCH_NODE"
    assert data["port"] == 5001

def test_batam_sentiment_auth():
    # 1. Without secret -> 401
    resp = client.post("/analyze_sentiment", json={"symbols": ["BTCIDR", "ETHIDR"]})
    assert resp.status_code == 401

    # 2. With secret -> 200
    headers = {"X-Kibot-Secret": CLUSTER_SECRET}
    resp2 = client.post("/analyze_sentiment", json={"symbols": ["BTCIDR", "ETHIDR"]}, headers=headers)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "SUCCESS"
    assert "BTCIDR" in data2["results"]

def test_batam_portfolio_optimization():
    headers = {"X-Kibot-Secret": CLUSTER_SECRET}
    payload = {"symbols": ["BTCIDR", "ETHIDR", "SOLIDR"], "target_risk": 0.12}
    resp = client.post("/optimize_portfolio", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert len(data["weights"]) == 3
    assert abs(sum(data["weights"].values()) - 1.0) < 0.01
