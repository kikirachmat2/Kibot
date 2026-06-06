import asyncio
import json
from pathlib import Path

from Core.Intelligence import kibot_ai_scout


def _write(path: Path, data: dict):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_runtime_patrol_detects_order_block_with_visible_targets(tmp_path, monkeypatch):
    monkeypatch.setattr(kibot_ai_scout, "STATE_DIR", tmp_path)
    monkeypatch.delenv("KIBOT_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("KIBOT_TELEGRAM_CHAT_ID", raising=False)

    _write(
        tmp_path / "capital_governor.json",
        {
            "allow_new_orders": False,
            "allow_new_orders_reason": "global_daily_loss_cap_breached",
            "global_hard_stop": True,
            "daily_reset_pending": True,
            "daily_reset_reason": "daily_rollover_exit_pending",
        },
    )
    _write(
        tmp_path / "live_order_dispatcher.json",
        {"status": "BLOCKED_WITH_REASON", "reason": "capital_governor_blocked"},
    )
    _write(
        tmp_path / "indodax_top_targets.json",
        {"top_targets": [{"recommended_action": "ENTER"}]},
    )
    _write(
        tmp_path / "indodax_scanner_state.json",
        {"source_status": "OK", "pairs_checked": 10, "candidates_found": 2},
    )
    _write(tmp_path / "active_trades.json", {"EDENA/IDR": {"amount": 1}})

    scout = kibot_ai_scout.WorldScout()
    semantics = scout._runtime_semantics()

    assert semantics["allow_new_orders"] is False
    assert semantics["global_hard_stop"] is True
    assert semantics["daily_reset_pending"] is True
    assert semantics["enter_targets"] == 1
    assert "opportunities_present_but_orders_blocked" in semantics["alerts"]
    assert any("orders_blocked" in item for item in semantics["alerts"])


def test_runtime_patrol_writes_telegram_status_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(kibot_ai_scout, "STATE_DIR", tmp_path)
    monkeypatch.setattr(kibot_ai_scout, "AI_PATROL_FILE", tmp_path / "ai_patrol.json")
    monkeypatch.setattr(kibot_ai_scout, "AI_TRACE_FILE", tmp_path / "ai_decision_trace.json")
    monkeypatch.delenv("KIBOT_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("KIBOT_TELEGRAM_CHAT_ID", raising=False)

    for name in (
        "capital_governor.json",
        "indodax_scanner_state.json",
        "scanner_executor_contract.json",
        "server_telemetry.json",
        "ai_decision_trace.json",
        "ai_strategy_review.json",
        "live_order_dispatcher.json",
        "indodax_top_targets.json",
    ):
        _write(tmp_path / name, {})

    scout = kibot_ai_scout.WorldScout()
    monkeypatch.setattr(scout, "_run_command", lambda *a, **k: {"ok": True, "stdout": "active", "stderr": ""})

    payload = asyncio.run(scout.perform_runtime_patrol())

    assert payload["telegram"]["configured"] is False
    assert "telegram_config_missing" in payload["alerts"]
    assert "runtime_semantics" in payload


def test_ai_patrol_does_not_send_telegram_for_auto_repairable_rollover(tmp_path, monkeypatch):
    monkeypatch.setattr(kibot_ai_scout, "STATE_DIR", tmp_path)

    _write(
        tmp_path / "capital_governor.json",
        {
            "allow_new_orders": False,
            "allow_new_orders_reason": "daily_rollover_exit_pending (1 open; symbols=POND/IDR)",
            "daily_reset_pending": True,
            "daily_reset_reason": "daily_rollover_exit_pending",
        },
    )
    _write(
        tmp_path / "live_order_dispatcher.json",
        {"status": "BLOCKED_WITH_REASON", "reason": "daily_rollover_exit_pending (1 open; symbols=POND/IDR)"},
    )
    _write(tmp_path / "indodax_top_targets.json", {"top_targets": [{"recommended_action": "ENTER"}]})

    scout = kibot_ai_scout.WorldScout()
    semantics = scout._runtime_semantics()

    assert scout._runtime_blocker_auto_repairable(semantics) is True
    assert asyncio.run(
        scout._notify_runtime_blockers(
            semantics,
            {"configured": True, "bot_api_ok": True},
        )
    ) is False
