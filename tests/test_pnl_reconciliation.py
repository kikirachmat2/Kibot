import json


def test_pnl_reconciliation_flags_anchor_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr("Core.Treasury.pnl_reconciliation.STATE", tmp_path)
    monkeypatch.setattr("Core.Treasury.pnl_reconciliation.OUT_FILE", tmp_path / "pnl_reconciliation.json")

    (tmp_path / "daily_equity_anchor.json").write_text(json.dumps({
        "date": "2026-05-20",
        "start_equity_idr": 150000.0,
        "max_daily_loss_idr": 2250.0,
    }))
    (tmp_path / "capital_governor.json").write_text(json.dumps({
        "date": "2026-05-20",
        "start_total_equity_idr": 280000.0,
        "current_total_equity_idr": 149000.0,
        "daily_pnl_idr": -131000.0,
        "max_daily_loss_idr": 4200.0,
        "allow_new_orders": True,
        "status": "RECONCILED",
    }))
    (tmp_path / "venue_ledger.json").write_text(json.dumps({
        "indodax_shadow": {"mode": "SHADOW", "equity_idr": 1000000}
    }))

    from Core.Treasury.pnl_reconciliation import reconcile_pnl_state

    state = reconcile_pnl_state(write=True)
    types = {item["type"] for item in state["discrepancies"]}
    assert "ANCHOR_GOVERNOR_MISMATCH" in types
    assert "LEGACY_LEDGER_ROWS" in types
    assert state["canonical"]["daily_pnl_idr"] == -1000.0


def test_pnl_reconciliation_blocks_when_canonical_hard_stop(monkeypatch, tmp_path):
    monkeypatch.setattr("Core.Treasury.pnl_reconciliation.STATE", tmp_path)
    monkeypatch.setattr("Core.Treasury.pnl_reconciliation.OUT_FILE", tmp_path / "pnl_reconciliation.json")

    (tmp_path / "daily_equity_anchor.json").write_text(json.dumps({
        "date": "2026-05-20",
        "start_equity_idr": 100000.0,
        "max_daily_loss_idr": 1500.0,
    }))
    (tmp_path / "capital_governor.json").write_text(json.dumps({
        "date": "2026-05-20",
        "start_total_equity_idr": 100000.0,
        "current_total_equity_idr": 98000.0,
        "daily_pnl_idr": -2000.0,
        "max_daily_loss_idr": 1500.0,
        "allow_new_orders": True,
        "status": "RECONCILED",
    }))

    from Core.Treasury.pnl_reconciliation import reconcile_pnl_state

    state = reconcile_pnl_state(write=True)
    assert state["canonical"]["hard_stop"] is True
    assert state["final_order_permission"]["allow_new_orders"] is False


def test_pnl_reconciliation_adjusts_external_flows(monkeypatch, tmp_path):
    monkeypatch.setattr("Core.Treasury.pnl_reconciliation.STATE", tmp_path)
    monkeypatch.setattr("Core.Treasury.pnl_reconciliation.OUT_FILE", tmp_path / "pnl_reconciliation.json")

    (tmp_path / "daily_equity_anchor.json").write_text(json.dumps({
        "date": "2026-05-20",
        "start_equity_idr": 100000.0,
        "max_daily_loss_idr": 1500.0,
    }))
    (tmp_path / "capital_governor.json").write_text(json.dumps({
        "date": "2026-05-20",
        "start_total_equity_idr": 100000.0,
        "current_total_equity_idr": 120000.0,
        "daily_pnl_idr": 10000.0,
        "external_deposits_today": 15000.0,
        "external_withdrawals_today": 5000.0,
        "reset_deposits_offset": 5000.0,
        "reset_withdrawals_offset": 0.0,
        "max_daily_loss_idr": 1500.0,
        "allow_new_orders": True,
        "status": "RECONCILED",
    }))

    from Core.Treasury.pnl_reconciliation import reconcile_pnl_state

    state = reconcile_pnl_state(write=True)
    assert state["canonical"]["adjusted_external_deposits_idr"] == 15000.0
    assert state["canonical"]["adjusted_external_withdrawals_idr"] == 5000.0
    assert state["canonical"]["daily_pnl_idr"] == 10000.0
