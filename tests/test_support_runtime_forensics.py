from __future__ import annotations

import json
from pathlib import Path

import pytest

import Core.ki_brain as ki_brain
import Core.sovereign_council as sovereign_council
import Core.Treasury.live_truth_manager as live_truth_manager
import Core.Support.no_trade_forensics as no_trade_forensics
import Core.Support.workflow_supervisor as workflow_supervisor


def test_kibrain_has_inspect_import():
    assert hasattr(ki_brain, "inspect")


def test_sovereign_council_evidence_bundle_initialized():
    source = Path("Core/sovereign_council.py").read_text(encoding="utf-8")
    guard = source.find("evidence_bundle: Dict[str, Any] = {}")
    use = source.find('"risk_status": str((evidence_bundle.get("risk_status")')
    assert guard != -1
    assert use != -1
    assert guard < use


def test_live_truth_marks_dust_unsellable(monkeypatch, tmp_path):
    monkeypatch.setattr(live_truth_manager, "STATE_DIR", tmp_path)
    monkeypatch.setattr(live_truth_manager, "LIVE_TRUTH_FILE", tmp_path / "live_truth.json")
    (tmp_path / "capital_governor.json").write_text(json.dumps({"venues": {"indodax": {"equity_idr": 10, "status": "RECONCILED"}}, "status": "RECONCILED", "daily_pnl_idr": 1.0}), encoding="utf-8")
    (tmp_path / "active_trades.json").write_text(json.dumps({"PEPE/IDR": {"amount": 0.7328859, "price": 1.0, "reason": "EXIT_MINIMUM_NOT_MET"}}), encoding="utf-8")
    (tmp_path / "orders" / "_index.json").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "orders" / "_index.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pnl_reconciliation.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pair_quarantine.json").write_text("{}", encoding="utf-8")
    (tmp_path / "trade_fees_today.json").write_text(json.dumps({"total_fee_idr": 0.0}), encoding="utf-8")
    payload = live_truth_manager.build_live_truth()
    assert payload["dust_positions"]
    assert payload["dust_positions"][0]["status"] == "DUST_UNSELLABLE"


def test_no_trade_forensics_written(monkeypatch, tmp_path):
    monkeypatch.setattr(no_trade_forensics, "STATE_DIR", tmp_path)
    monkeypatch.setattr(no_trade_forensics, "FORENSICS_FILE", tmp_path / "no_trade_forensics.json")
    for name, payload in {
        "workflow_automation.json": {
            "overall_status": "TRADING_FLOW_BLOCKED_WITH_REASON",
            "current_best_action": "WAIT",
            "money_truth": {"total_balance_idr": 1000, "daily_return_idr": -1, "daily_return_pct": -0.1, "allow_new_orders": False, "allow_new_orders_reason": "orders_disabled"},
            "blockers": [{"source": "capital_governor", "reason": "orders_disabled"}],
        },
        "live_truth.json": {"open_positions": [], "dust_positions": [{"pair": "PEPE/IDR"}], "venue_locks": {}},
        "capital_governor.json": {"allow_new_orders_reason": "orders_disabled"},
        "live_order_dispatcher.json": {"reason": "blocked"},
        "ai_patrol.json": {"support_action": "monitor"},
        "indodax_top_targets.json": {"top_targets": []},
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    payload = no_trade_forensics.build_no_trade_forensics()
    assert payload["classification"] in {"CAPITAL_BOTTLENECK", "BROKEN_WAIT", "HEALTHY_WAIT", "STRATEGY_NO_EDGE"}
    assert (tmp_path / "no_trade_forensics.json").exists()
