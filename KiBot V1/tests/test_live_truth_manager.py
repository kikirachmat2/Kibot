from __future__ import annotations

import json
from pathlib import Path

from Core.Treasury.live_truth_manager import build_live_truth, load_live_truth
import Core.Treasury.live_truth_manager as live_truth_module


def test_live_truth_manager_writes_schema():
    payload = build_live_truth()
    assert payload["runtime_mode"] == "LIVE_ONLY"
    assert "updated_at" in payload
    assert "indodax" in payload
    assert ("ph" + "antom") not in payload
    assert payload.get("platform_mode") == "INDODAX_ONLY"
    state = Path("state/live_truth.json")
    assert state.exists()
    loaded = load_live_truth()
    assert isinstance(loaded, dict)
    assert loaded.get("runtime_mode") == "LIVE_ONLY"
    json.loads(state.read_text(encoding="utf-8"))


def test_live_truth_infers_cash_from_governor_when_portfolio_cash_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(live_truth_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(live_truth_module, "LIVE_TRUTH_FILE", tmp_path / "live_truth.json")
    (tmp_path / "capital_governor.json").write_text(json.dumps({
        "status": "RECONCILED",
        "daily_pnl_idr": 500.0,
        "current_total_equity_idr": 125000.0,
        "open_buy_order_reserve_idr": 0.0,
        "venues": {"indodax": {"status": "RECONCILED", "equity_idr": 125000.0}},
    }), encoding="utf-8")
    (tmp_path / "portfolio_summary.json").write_text("{}", encoding="utf-8")
    (tmp_path / "active_trades.json").write_text("{}", encoding="utf-8")
    (tmp_path / "orders").mkdir(parents=True)
    (tmp_path / "orders" / "_index.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pnl_reconciliation.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pair_quarantine.json").write_text("{}", encoding="utf-8")

    payload = build_live_truth()

    assert payload["total_equity_idr"] == 125000.0
    assert payload["cash_idr"] == 125000.0
    assert payload["accounting_breakdown"]["cash_source"] == "capital_governor_inferred"


def test_live_truth_fee_breakdown_does_not_double_subtract_from_equity_pnl(monkeypatch, tmp_path):
    monkeypatch.setattr(live_truth_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(live_truth_module, "LIVE_TRUTH_FILE", tmp_path / "live_truth.json")
    (tmp_path / "capital_governor.json").write_text(json.dumps({
        "status": "RECONCILED",
        "daily_pnl_idr": -1000.0,
        "current_total_equity_idr": 99000.0,
        "venues": {"indodax": {"status": "RECONCILED", "equity_idr": 99000.0}},
    }), encoding="utf-8")
    (tmp_path / "portfolio_summary.json").write_text("{}", encoding="utf-8")
    (tmp_path / "active_trades.json").write_text("{}", encoding="utf-8")
    (tmp_path / "orders").mkdir(parents=True)
    (tmp_path / "orders" / "_index.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pnl_reconciliation.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pair_quarantine.json").write_text("{}", encoding="utf-8")
    (tmp_path / "trade_fees_today.json").write_text(json.dumps({"total_fee_idr": 250.0}), encoding="utf-8")

    payload = build_live_truth()

    assert payload["fees_today_idr"] == 250.0
    assert payload["net_pnl_today_idr"] == -1000.0
    assert payload["accounting_breakdown"]["fees_are_breakdown_not_double_subtracted"] is True
