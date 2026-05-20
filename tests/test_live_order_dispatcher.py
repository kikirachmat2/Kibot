import json
from pathlib import Path

from Core.Decision import live_order_dispatcher as dispatcher
from Core.Decision.live_order_dispatcher import LiveOrderDispatcher


def test_live_dispatcher_builds_indodax_council_mandate(monkeypatch, tmp_path):
    monkeypatch.setattr(dispatcher, "STATE_DIR", tmp_path)
    monkeypatch.setattr(dispatcher, "STATE_FILE", tmp_path / "live_order_dispatcher.json")
    (tmp_path / "capital_governor.json").write_text(json.dumps({
        "current_total_equity_idr": 188290,
        "max_daily_loss_idr": 2824.35,
        "trading_pnl_idr": 0,
    }))
    d = LiveOrderDispatcher()
    signal = d._build_indodax_signal({
        "symbol": "EDEN/IDR",
        "last_price": 1515,
        "change_24h_pct": 81.4,
        "entry_score": 286.55,
        "volume_24h_idr": 2_700_000_000,
        "source_proof_ok": True,
    })
    assert signal["type"] == "COUNCIL_MANDATE"
    assert signal["symbol"] == "EDEN/IDR"
    assert signal["budget_idr"] >= 10_000
    assert signal["max_spread_pct"] >= 1.0


def test_live_dispatcher_skips_active_symbol(monkeypatch, tmp_path):
    monkeypatch.setattr(dispatcher, "STATE_DIR", tmp_path)
    monkeypatch.setattr(dispatcher, "STATE_FILE", tmp_path / "live_order_dispatcher.json")
    (tmp_path / "active_trades.json").write_text(json.dumps({"EDEN/IDR": {"cost": 10000}}))
    (tmp_path / "indodax_top_targets.json").write_text(json.dumps({
        "top_targets": [{
            "symbol": "EDEN/IDR",
            "recommended_action": "ENTER",
            "route_status": "EXECUTABLE",
            "source_proof_ok": True,
        }]
    }))
    assert LiveOrderDispatcher()._indodax_candidates() == []


def test_live_dispatcher_blocks_on_global_hard_stop(monkeypatch, tmp_path):
    monkeypatch.setattr(dispatcher, "STATE_DIR", tmp_path)
    monkeypatch.setattr(dispatcher, "STATE_FILE", tmp_path / "live_order_dispatcher.json")
    monkeypatch.setattr(dispatcher.KiConfig, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setenv("KIBOT_SECRET", "unit-test-secret")
    (tmp_path / "capital_governor.json").write_text(json.dumps({
        "allow_new_orders": False,
        "status": "BLOCKED_WITH_REASON",
        "allow_new_orders_reason": "global_daily_loss_cap_breached (-6000.00 <= -5000.00)",
        "daily_pnl_idr": -6000.0,
        "max_daily_loss_idr": 5000.0,
    }))
    dispatcher_instance = LiveOrderDispatcher()
    result = dispatcher_instance.dispatch_indodax_once()
    assert result["status"] == "BLOCKED_WITH_REASON"
    assert "global_daily_loss_cap_breached" in result["reason"]
