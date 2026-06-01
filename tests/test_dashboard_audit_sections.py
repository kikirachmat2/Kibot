from __future__ import annotations

from fastapi.testclient import TestClient

from Core.Intelligence.kibot_dashboard import app


client = TestClient(app)


def test_control_plane_exposes_new_audit_sections():
    payload = client.get("/api/control-plane").json()
    for key in (
        "target_freshness_audit",
        "ai_actual_usage_audit",
        "autonomous_runtime_readiness_audit",
        "server_extensions_usage_audit",
        "repo_safety_audit",
        "trading_decision_policy_audit",
    ):
        assert key in payload, f"{key} missing from control-plane payload"
