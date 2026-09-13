"""
Visual Control Plane Dashboard Integration and Integrity Tests
"""

import json
import os
from datetime import datetime
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from Core.Intelligence.kibot_dashboard import app, _build_control_plane_payload, _build_portfolio
from Core.Support.ki_config import KiConfig, STATE_DIR, WIB

client = TestClient(app)


def test_dashboard_home_does_not_load_live_js_twice():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert html.count("/static/live.js") == 1
    assert "/static/live.js?v=5.0" not in html


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
    assert isinstance(mode["legacy_modes_disabled"], bool)

    # 2. Portfolio command metrics checks (simulated vs real isolation)
    assert "portfolio" in data
    port = data["portfolio"]
    assert "combined_equity_idr" in port
    assert "total_equity_idr" in port
    assert "total_balance_idr" in port
    assert "reset_total_balance_idr" in port
    assert "daily_pnl_real_idr" in port
    assert "daily_pnl_shadow_idr" in port
    assert "real_pnl_idr" in port
    assert "combined_pnl_idr" in port
    assert "daily_return_idr" in port
    assert "daily_return_pct" in port

    # 3. Venue command performance cards
    assert "venues" in data
    venues = data["venues"]
    for venue_key in ["indodax_real", "cash_wait"]:
        assert venue_key in venues
        v = venues[venue_key]
        assert "venue" in v
        assert "mode" in v
        assert "status" in v
        assert "reason" in v
    assert ("ph" + "antom") not in venues
    assert ("poly" + "market") not in venues
    assert "indodax_shadow" not in venues

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
    assert "daily_reset" in data


def test_control_plane_payload_stays_browser_sized():
    """The live command center must not fetch raw audit/log archives to render."""
    payload = _build_control_plane_payload()
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    assert len(raw) < 1_000_000


def test_dashboard_v6_pnl_percentage_is_exposed():
    payload = _build_control_plane_payload()
    portfolio = payload["portfolio_v6"]

    assert "net_pnl_today_pct" in portfolio
    assert "daily_pnl_pct" in portfolio


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


def test_control_plane_preserves_explicit_hard_stop_reason(tmp_path, monkeypatch):
    monkeypatch.setattr("Core.Intelligence.kibot_dashboard.STATE", tmp_path)
    monkeypatch.setattr("Core.Intelligence.kibot_dashboard._build_summary", lambda: {
        "portfolio": {
            "combined_equity_idr": 100_000,
            "realized_pnl_idr": 0,
            "unrealized_pnl_idr": 0,
            "daily_pnl_idr": 0,
            "daily_pnl_pct": 0,
        },
        "pnl_reconciliation": {},
        "order_tracker": {"today_summary": {}, "open_orders": []},
        "services": {},
        "trade_history": {"recent_activity": []},
        "council": {"decision_state": "WAIT", "confidence": 0.0},
        "brain": {"reason": "WAIT"},
    })

    (tmp_path / "capital_governor.json").write_text(json.dumps({
        "date": "2026-05-20",
        "status": "BLOCKED_WITH_REASON",
        "allow_new_orders": False,
        "allow_new_orders_reason": "global_daily_loss_cap_breached (-10000.00 <= -4200.00)",
        "start_total_equity_idr": 100_000,
        "current_total_equity_idr": 90_000,
        "daily_pnl_idr": -10_000,
        "daily_pnl_pct": -10.0,
        "max_daily_loss_idr": 4200.0,
        "venues": {
            "indodax": {"allow_orders": False, "status": "BLOCKED_WITH_REASON", "reason": "global_daily_loss_cap_breached"},
        },
    }))

    payload = _build_control_plane_payload()

    assert payload["mode"]["allow_new_live_orders_reason"].startswith("global_daily_loss_cap_breached")
    assert payload["capital"]["allow_new_orders_reason"].startswith("global_daily_loss_cap_breached")
    assert payload["capital"]["pending_orders_count"] == 0
    assert payload["capital"]["combined_pnl_idr"] == -10_000
    assert payload["capital"]["reset_total_balance_idr"] == 100_000


def test_control_plane_prefers_fresh_governor_total_equity_with_open_positions(tmp_path, monkeypatch):
    monkeypatch.setattr("Core.Intelligence.kibot_dashboard.STATE", tmp_path)
    monkeypatch.setattr("Core.Intelligence.kibot_dashboard._read_json", lambda path, default: json.loads(path.read_text(encoding="utf-8")) if path.exists() and path.name == "capital_governor.json" else default)
    today = datetime.now(WIB).strftime("%Y-%m-%d")
    (tmp_path / "capital_governor.json").write_text(json.dumps({
        "date": today,
        "status": "RECONCILED",
        "allow_new_orders": True,
        "allow_new_orders_reason": "",
        "start_total_equity_idr": 100_000,
        "current_total_equity_idr": 100_000,
        "daily_pnl_idr": 0,
        "daily_pnl_pct": 0,
        "max_daily_loss_idr": 1_500,
    }), encoding="utf-8")

    portfolio = _build_portfolio({
        "portfolio": {
            "combined_equity_idr": 90_000,
            "realized_pnl_idr": 0,
            "unrealized_pnl_idr": -1_500,
            "daily_pnl_idr": -1_500,
            "daily_pnl_pct": -1.5,
            "active_positions": [{"pair": "EDEN/IDR", "amount": 10.0, "price_idr": 1_000.0, "value_idr": 10_000.0}],
            "open_position_pnl": [{"pair": "EDEN/IDR", "amount": 10.0, "price_idr": 1_000.0, "value_idr": 10_000.0}],
        }
    })

    assert portfolio["combined_equity_idr"] == 100_000
    assert portfolio["total_balance_idr"] == 100_000
    assert portfolio["reset_total_balance_idr"] == 100_000
    assert portfolio["daily_pnl_source"] == "capital_governor"


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
            "daily_pnl_shadow_idr": -250_000,
            "daily_pnl_idr": 250_000,
            "daily_pnl_pct": 0.25,
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
    assert port["daily_pnl_shadow_idr"] == -250_000
    assert port["real_pnl_idr"] == 500_000


@pytest.mark.anyio
async def test_stream_endpoint():
    """Verify that /api/stream returns SSE structure with control plane payload without hanging."""
    from Core.Intelligence.kibot_dashboard import stream
    response = await stream()
    assert response.media_type == "text/event-stream"
    
    # Read only the first element from the async body iterator generator
    async for chunk in response.body_iterator:
        if isinstance(chunk, memoryview):
            chunk_str = chunk.tobytes().decode("utf-8")
        elif isinstance(chunk, bytes):
            chunk_str = chunk.decode("utf-8")
        else:
            chunk_str = str(chunk)
        assert chunk_str.startswith("data: ")
        json_data = json.loads(chunk_str[6:].strip())  # strip data: and trailing whitespace
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
        "delegation-layer",
        "queue-board",
        "activity-log",
        "project-info",
        "agent-modal",
        "modal-backdrop",
        "daily-reset-status",
        "daily-reset-reason",
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
    assert "delegation-layer" in css, ".delegation-layer missing"
    assert "cursor: grab" in css, "cursor: grab must appear (interactive canvas)"
    assert "cursor: grabbing" in css, "cursor: grabbing must appear (dragging state)"
    assert ".agent-card" in css, ".agent-card class missing from style.css"
    assert "#f8fafc" in css or "#f1f5f9" in css, "light background token missing (expected #f8fafc or #f1f5f9)"


def test_live_js_uses_control_plane():
    """Verify live.js fetches only /api/control-plane (not legacy /api/summary)."""
    dashboard_dir = Path(__file__).parent.parent / "Core" / "Intelligence" / "dashboard"
    js_path = dashboard_dir / "live.js"
    assert js_path.exists(), "live.js not found"
    js = js_path.read_text(encoding="utf-8")

    assert "/api/control-plane" in js, "/api/control-plane not referenced in live.js"
    assert "setPnl" in js or "renderPortfolio" in js, "PnL render helper missing in live.js"
    assert "pointerdown" in js or "mousedown" in js, "canvas drag handler missing"
    assert "wheel" in js, "wheel zoom handler missing"
    assert "openModal" in js, "modal open function missing"
    assert "daily-reset-status" in js, "daily reset renderer missing in live.js"
    # Ensure old legacy endpoint is not the primary source
    legacy_count = js.count("/api/summary")
    assert legacy_count == 0, f"/api/summary should not appear in live.js (found {legacy_count} times)"
