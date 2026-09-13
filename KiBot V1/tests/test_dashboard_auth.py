from fastapi.testclient import TestClient
import os
import base64
from Core.Intelligence.kibot_dashboard import app

def test_dashboard_authentication_required_and_success():
    client = TestClient(app)
    
    # 1. Without credentials -> HTTP 401 (with X-Test-Auth-Check: true)
    unauth_res = client.get("/api/control-plane", headers={"X-Test-Auth-Check": "true"})
    assert unauth_res.status_code == 401
    assert "Unauthorized" in unauth_res.text
    
    # 2. Healthz endpoint is exempt -> HTTP 200
    health_res = client.get("/api/healthz", headers={"X-Test-Auth-Check": "true"})
    assert health_res.status_code == 200
    assert health_res.json().get("ok") is True
    
    # 3. With correct credentials -> HTTP 200
    user = os.getenv("KIBOT_DASHBOARD_USER", "admin")
    pwd = os.getenv("KIBOT_DASHBOARD_PASSWORD", "DO5WoVjSb5eHIpHgrewHTIFAVrcJzMr9")
    token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    auth_res = client.get("/api/control-plane", headers={"Authorization": f"Basic {token}", "X-Test-Auth-Check": "true"})
    assert auth_res.status_code == 200
    assert "system_truth" in auth_res.json()
