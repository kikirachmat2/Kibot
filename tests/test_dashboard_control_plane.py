"""
Visual Control Plane Dashboard Integration and Integrity Tests
"""

import json
import os
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from Core.Intelligence.kibot_dashboard import app, _build_control_plane_payload
from Core.Support.ki_config import KiConfig, STATE_DIR

client = TestClient(app)


def test_control_plane_payload_structure():
    """Verify that /api/control-plane returns the correct sci-fi console structure."""
    response = client.get("/api/control-plane")
    assert response.status_code == 200
    
    data = response.json()
    
    # 1. Mode config checks
    assert "mode" in data
    mode = data["mode"]
    assert "trading_mode" in mode
    assert isinstance(mode["live_trading_enabled"], bool)
    assert isinstance(mode["canary_enabled"], bool)
    assert isinstance(mode["real_swap_enabled"], bool)
    assert isinstance(mode["real_bridge_enabled"], bool)
    assert isinstance(mode["real_withdrawal_enabled"], bool)

    # 2. Portfolio command metrics checks (simulated vs real isolation)
    assert "portfolio" in data
    port = data["portfolio"]
    assert "combined_equity_idr" in port
    assert "total_equity_idr" in port
    assert "daily_pnl_real_idr" in port
    assert "daily_pnl_sim_idr" in port
    assert "real_pnl_idr" in port
    assert "mock_pnl_idr" in port
    assert "simulated_pnl_idr" in port

    # 3. Venue command performance cards
    assert "venues" in data
    venues = data["venues"]
    for venue_key in ["indodax_real", "indodax_paper", "phantom", "polymarket", "cash_wait"]:
        assert venue_key in venues
        v = venues[venue_key]
        assert "venue" in v
        assert "mode" in v
        assert "status" in v
        assert "reason" in v

    # 4. Intelligence Gate Stack
    assert "gates" in data
    gates = data["gates"]
    for gate_key in ["signal_quality", "expected_value", "strategy_scorecard", "punishment", "risk_gate", "microstructure"]:
        assert gate_key in gates
        g = gates[gate_key]
        assert "status" in g
        if gate_key == "risk_gate":
            assert g["max_drawdown_limit"] == 1.5

    # 5. Runtime diagnostic checks
    assert "runtime" in data
    runtime = data["runtime"]
    for r_key in ["scanner", "leadlag", "market_rotation", "autonomous_director", "healthcheck", "ollama"]:
        assert r_key in runtime
        assert "status" in runtime[r_key]

    # 6. Flow nodes connections
    assert "flow" in data
    assert isinstance(data["flow"], list)
    assert len(data["flow"]) > 0
    for edge in data["flow"]:
        assert "from" in edge
        assert "to" in edge

    # 7. Warnings and decisions
    assert "warnings" in data
    assert isinstance(data["warnings"], list)
    assert "recent_decisions" in data
    assert isinstance(data["recent_decisions"], list)


def test_zero_secret_leak(monkeypatch):
    """Ensure no raw secrets or private keys are leaked in the dashboard payload."""
    monkeypatch.setenv("KIBOT_SECRET_KEY", "super_secret_value_12345")
    monkeypatch.setenv("INDODAX_API_KEY", "indo_api_key_xyz")
    monkeypatch.setenv("INDODAX_SECRET_KEY", "indo_secret_key_abc")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tg_token_9876")

    response = client.get("/api/control-plane")
    assert response.status_code == 200
    
    raw_payload_str = response.text
    
    assert "super_secret_value_12345" not in raw_payload_str
    assert "indo_api_key_xyz" not in raw_payload_str
    assert "indo_secret_key_abc" not in raw_payload_str
    assert "tg_token_9876" not in raw_payload_str


def test_missing_files_graceful(tmp_path, monkeypatch):
    """Verify endpoint runs gracefully even if state files are completely missing."""
    # Point STATE_DIR to an empty temp directory
    monkeypatch.setattr("Core.Intelligence.kibot_dashboard.STATE", tmp_path)
    
    # Endpoint should not crash and should return standard UNKNOWN or default statuses
    response = client.get("/api/control-plane")
    assert response.status_code == 200
    data = response.json()
    assert data["gates"]["signal_quality"]["status"] == "WAIT"
    assert data["gates"]["expected_value"]["status"] == "WAIT"
    assert data["gates"]["strategy_scorecard"]["status"] == "WAIT"


def test_simulated_vs_real_pnl_isolation(tmp_path, monkeypatch):
    """Verify absolute isolation of real and mock PnL values."""
    monkeypatch.setattr("Core.Intelligence.kibot_dashboard.STATE", tmp_path)
    
    # Mock a summary file containing explicit PnL metrics
    summary_mock = {
        "portfolio": {
            "combined_equity_idr": 100_000_000,
            "equity_idr": 45_000_000,
            "idr_cash": 15_000_000,
            "coin_holdings_idr": 30_000_000,
            "daily_pnl_real_idr": 500_000,
            "daily_pnl_sim_idr": -250_000,
            "daily_pnl_idr": 250_000,
            "daily_pnl_pct": 0.25,
            "phantom": {
                "opportunity_pnl_idr": 75_000
            }
        }
    }
    
    def mock_build_summary():
        return summary_mock
        
    monkeypatch.setattr("Core.Intelligence.kibot_dashboard._build_summary", mock_build_summary)
    
    response = client.get("/api/control-plane")
    assert response.status_code == 200
    data = response.json()
    
    port = data["portfolio"]
    assert port["daily_pnl_real_idr"] == 500_000
    assert port["daily_pnl_sim_idr"] == -250_000
    assert port["real_pnl_idr"] == 500_000
    assert port["mock_pnl_idr"] == -250_000
    assert port["simulated_pnl_idr"] == 75_000


@pytest.mark.anyio
async def test_stream_endpoint():
    """Verify that /api/stream returns SSE structure with control plane payload without hanging."""
    from Core.Intelligence.kibot_dashboard import stream
    response = await stream()
    assert response.media_type == "text/event-stream"
    
    # Read only the first element from the async body iterator generator
    async for chunk in response.body_iterator:
        assert chunk.startswith("data: ")
        json_data = json.loads(chunk[6:].strip())  # strip data: and trailing whitespace
        assert "mode" in json_data
        assert "portfolio" in json_data
        assert "venues" in json_data
        assert "gates" in json_data
        break  # exit immediately to prevent infinite loop


def test_freshness_block_in_payload():
    """Verify the freshness block is present in /api/control-plane."""
    response = client.get("/api/control-plane")
    assert response.status_code == 200
    data = response.json()
    assert "freshness" in data, "freshness block missing from control-plane payload"
    freshness = data["freshness"]
    expected_keys = [
        "scanner_runtime_age_s",
        "autonomous_director_age_s",
        "expected_value_age_s",
        "signal_quality_age_s",
        "telemetry_age_s",
    ]
    for key in expected_keys:
        assert key in freshness, f"freshness.{key} missing"
        assert isinstance(freshness[key], (int, float)), f"freshness.{key} must be numeric"


def test_html_contains_delegation_ids():
    """Verify index.html contains required Delegation-style component IDs and classes."""
    dashboard_dir = Path(__file__).parent.parent / "Core" / "Intelligence" / "dashboard"
    html_path = dashboard_dir / "index.html"
    assert html_path.exists(), "index.html not found"
    html = html_path.read_text(encoding="utf-8")

    required_ids = [
        "delegation-canvas",
        "agent-grid",
        "queue-board",
        "activity-log",
        "project-info",
    ]
    # Check either id= or class= presence of each key string
    for token in required_ids:
        assert token in html, f"'{token}' not found in index.html"

    required_classes = [
        "agent-card",
        "queue-lane",
        "top-bar",
        "workspace",
        "left-panel",
        "right-panel",
    ]
    for cls in required_classes:
        assert cls in html, f"class '{cls}' not found in index.html"


def test_css_contains_no_scroll_rules():
    """Verify style.css enforces no body scroll and correct layout tokens."""
    dashboard_dir = Path(__file__).parent.parent / "Core" / "Intelligence" / "dashboard"
    css_path = dashboard_dir / "style.css"
    assert css_path.exists(), "style.css not found"
    css = css_path.read_text(encoding="utf-8")

    assert "overflow: hidden" in css, "overflow: hidden must appear in style.css (no-body-scroll rule)"
    assert ".workspace" in css, ".workspace class missing from style.css"
    assert ".delegation-canvas" in css or "delegation-canvas" in css, ".delegation-canvas missing"
    assert ".agent-card" in css, ".agent-card class missing from style.css"
    assert "#f8fafc" in css or "#f1f5f9" in css, "light background token missing (expected #f8fafc or #f1f5f9)"


def test_live_js_uses_control_plane():
    """Verify live.js fetches only /api/control-plane (not legacy /api/summary)."""
    dashboard_dir = Path(__file__).parent.parent / "Core" / "Intelligence" / "dashboard"
    js_path = dashboard_dir / "live.js"
    assert js_path.exists(), "live.js not found"
    js = js_path.read_text(encoding="utf-8")

    assert "/api/control-plane" in js, "/api/control-plane not referenced in live.js"
    assert "renderPnlEl" in js or "renderPortfolio" in js, "PnL render helper missing in live.js"
    # Ensure old legacy endpoint is not the primary source
    legacy_count = js.count("/api/summary")
    assert legacy_count == 0, f"/api/summary should not appear in live.js (found {legacy_count} times)"
