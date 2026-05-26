import json
from pathlib import Path

from Core.Support import workflow_supervisor


def _write(path: Path, data: dict):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_workflow_supervisor_explains_dispatcher_block(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow_supervisor, "STATE", tmp_path)
    monkeypatch.setattr(workflow_supervisor, "STATE_FILE", tmp_path / "workflow_automation.json")
    monkeypatch.setattr(
        workflow_supervisor,
        "_service_statuses",
        lambda: {name: {"active": True, "raw": "active"} for name in workflow_supervisor.CRITICAL_SERVICES},
    )
    monkeypatch.setattr(
        workflow_supervisor,
        "_telegram_status",
        lambda: {"configured": True, "bot_api_ok": True, "reason": "", "throttle_age_s": 1},
    )

    _write(
        tmp_path / "capital_governor.json",
        {
            "allow_new_orders": True,
            "allow_new_orders_reason": "venue-scoped allowances active: phantom",
            "total_balance_idr": 120000,
            "reset_total_balance_idr": 119000,
            "daily_return_idr": 1000,
            "daily_return_pct": 0.84,
        },
    )
    _write(
        tmp_path / "live_order_dispatcher.json",
        {
            "status": "BLOCKED_WITH_REASON",
            "indodax": {"reason": "indodax_daily_loss_cap_breached"},
            "phantom": {"reason": "sol_balance_below_trade_min"},
        },
    )
    _write(tmp_path / "indodax_top_targets.json", {"top_targets": [{"recommended_action": "ENTER"}]})
    _write(tmp_path / "phantom_top_targets.json", {"top_targets": []})
    _write(tmp_path / "ai_patrol.json", {"support_action": "continue", "alerts": []})

    state = workflow_supervisor.build_workflow_automation_state()

    assert state["overall_status"] == "TRADING_FLOW_BLOCKED_WITH_REASON"
    assert "indodax_daily_loss_cap_breached" in state["dispatcher"]["reason"]
    assert state["target_summary"]["enter_targets"] == 1
    assert state["money_truth"]["total_balance_idr"] == 120000
    assert state["remediation_plan"][0]["action"] == "RECOVERY_EXIT_ONLY_UNTIL_NEXT_DAILY_RESET"


def test_workflow_supervisor_ready_when_dispatcher_active(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow_supervisor, "STATE", tmp_path)
    monkeypatch.setattr(
        workflow_supervisor,
        "_service_statuses",
        lambda: {name: {"active": True, "raw": "active"} for name in workflow_supervisor.CRITICAL_SERVICES},
    )
    monkeypatch.setattr(
        workflow_supervisor,
        "_telegram_status",
        lambda: {"configured": True, "bot_api_ok": True, "reason": "", "throttle_age_s": 1},
    )

    _write(tmp_path / "capital_governor.json", {"allow_new_orders": True, "total_balance_idr": 100000})
    _write(tmp_path / "live_order_dispatcher.json", {"status": "ACTIVE"})
    _write(tmp_path / "indodax_top_targets.json", {"top_targets": [{"recommended_action": "ENTER"}]})
    _write(tmp_path / "phantom_top_targets.json", {"top_targets": []})

    state = workflow_supervisor.build_workflow_automation_state()

    assert state["overall_status"] == "TRADING_FLOW_READY"
    assert state["current_best_action"] == "dispatcher may enter eligible candidate"


def test_workflow_supervisor_remediates_rollover_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow_supervisor, "STATE", tmp_path)
    monkeypatch.setattr(
        workflow_supervisor,
        "_service_statuses",
        lambda: {name: {"active": True, "raw": "active"} for name in workflow_supervisor.CRITICAL_SERVICES},
    )
    monkeypatch.setattr(
        workflow_supervisor,
        "_telegram_status",
        lambda: {"configured": True, "bot_api_ok": True, "reason": "", "throttle_age_s": 1},
    )

    reason = "daily_rollover_exit_pending (2 open; symbols=POND/IDR)"
    _write(tmp_path / "capital_governor.json", {"allow_new_orders": False, "allow_new_orders_reason": reason})
    _write(tmp_path / "live_order_dispatcher.json", {"status": "BLOCKED_WITH_REASON", "reason": reason})
    _write(tmp_path / "indodax_top_targets.json", {"top_targets": [{"recommended_action": "ENTER"}]})
    _write(tmp_path / "phantom_top_targets.json", {"top_targets": []})

    state = workflow_supervisor.build_workflow_automation_state()

    assert state["current_best_action"] == "EXIT_OR_RECONCILE_OPEN_ROLLOVER_POSITION"
    assert state["remediation_plan"][0]["owner"] == "kibot-executor + daily-reset"
