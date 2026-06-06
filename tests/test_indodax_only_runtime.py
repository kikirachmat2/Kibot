from __future__ import annotations

import json

from Core.Decision import live_order_dispatcher as dispatcher
from Core.Decision.live_order_dispatcher import LiveOrderDispatcher
from Core.Intelligence.market_rotation import MarketRotationEngine
from Core.Support.ki_config import KiConfig
from Core.Treasury.live_truth_manager import build_live_truth


def test_indodax_only_config_disables_web3_routes():
    assert KiConfig.INDODAX_ONLY is True
    assert KiConfig.PHANTOM_ENABLED is False
    assert KiConfig.ENABLE_REAL_SWAP is False
    assert KiConfig.ENABLE_REAL_BRIDGE is False
    assert KiConfig.ENABLE_REAL_WITHDRAWAL is False
    assert KiConfig.ENABLE_POLYMARKET_LIVE is False
    assert KiConfig.SCANNER_ENABLE_WEB3 is False
    assert KiConfig.SCANNER_ENABLE_POLYMARKET is False


def test_live_truth_is_indodax_only(monkeypatch, tmp_path):
    import Core.Treasury.live_truth_manager as live_truth_module

    monkeypatch.setattr(live_truth_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(live_truth_module, "LIVE_TRUTH_FILE", tmp_path / "live_truth.json")
    (tmp_path / "capital_governor.json").write_text(json.dumps({
        "venues": {"indodax": {"status": "RECONCILED", "equity_idr": 123000, "allow_orders": True}},
        "daily_pnl_idr": 500,
    }))
    payload = build_live_truth()
    assert payload["platform_mode"] == "INDODAX_ONLY"
    assert payload["total_equity_idr"] == 123000
    assert "phantom" not in payload
    assert payload["retired_venues"]["phantom"]["status"] == "REMOVED_BY_OPERATOR"


def test_live_dispatcher_does_not_dispatch_phantom(monkeypatch, tmp_path):
    monkeypatch.setattr(dispatcher, "STATE_DIR", tmp_path)
    monkeypatch.setattr(dispatcher, "STATE_FILE", tmp_path / "live_order_dispatcher.json")
    monkeypatch.setattr(dispatcher.KiConfig, "LIVE_TRADING_ENABLED", True)
    (tmp_path / "capital_governor.json").write_text(json.dumps({
        "allow_new_orders": False,
        "status": "BLOCKED_WITH_REASON",
        "allow_new_orders_reason": "unit-test",
    }))
    state = __import__("asyncio").run(LiveOrderDispatcher().tick())
    assert "phantom" not in state
    assert state["retired_venues"]["phantom"]["status"] == "REMOVED_BY_OPERATOR"


def test_market_rotation_is_indodax_cash_only(monkeypatch, tmp_path):
    engine = MarketRotationEngine()
    engine.state_file = str(tmp_path / "market_rotation.json")
    engine.last_allocation = {}
    result = __import__("asyncio").run(engine.compute_optimal_allocation(100000))
    assert result["platform_mode"] == "INDODAX_ONLY"
    assert result["allocations_pct"] == {"Indodax": 85.0, "CASH_WAIT": 15.0}
    assert "Phantom" not in result["allocations_pct"]
    assert "Polymarket" not in result["allocations_pct"]
