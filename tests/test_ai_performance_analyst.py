"""Unit tests for AI Performance Analyst out-of-band module."""

import json
from pathlib import Path
import pytest

from Core.Intelligence.ai_performance_analyst import (
    collect_performance_metrics,
    run_performance_analysis,
    get_latest_report,
)


@pytest.fixture
def temp_analyst_env(tmp_path, monkeypatch):
    import Core.Intelligence.ai_performance_analyst as analyst_mod
    import Core.Intelligence.trade_history as th_mod

    state_dir = tmp_path / "state"
    history_dir = state_dir / "trade_history"
    history_dir.mkdir(parents=True, exist_ok=True)
    report_file = state_dir / "ai_performance_report.json"

    monkeypatch.setattr(analyst_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(analyst_mod, "AI_REPORT_FILE", report_file)
    monkeypatch.setattr(th_mod, "HISTORY_DIR", history_dir)

    # Populate mock trade history
    trade1 = {
        "status": "CLOSED",
        "variant_id": "CONSERVATIVE",
        "pair": "BTC/IDR",
        "exit_reason": "TAKE_PROFIT_TARGET_HIT",
        "realized_pnl_pct": 3.5,
        "realized_pnl_idr": 8750.0,
    }
    trade2 = {
        "status": "CLOSED",
        "variant_id": "CONSERVATIVE",
        "pair": "ETH/IDR",
        "exit_reason": "STOP_LOSS_BREACHED",
        "realized_pnl_pct": -1.5,
        "realized_pnl_idr": -3750.0,
    }
    f1 = history_dir / "paper_2026-08-13.jsonl"
    f1.write_text(json.dumps(trade1) + "\n" + json.dumps(trade2) + "\n", encoding="utf-8")

    return state_dir, history_dir, report_file


def test_collect_performance_metrics(temp_analyst_env):
    state_dir, history_dir, report_file = temp_analyst_env
    metrics = collect_performance_metrics()

    assert "variant_stats" in metrics
    cons = metrics["variant_stats"]["CONSERVATIVE"]
    assert cons["total_trades"] == 2
    assert cons["wins"] == 1
    assert cons["losses"] == 1
    assert cons["win_rate_pct"] == 50.0
    assert cons["exit_reasons"]["TAKE_PROFIT_TARGET_HIT"] == 1
    assert cons["exit_reasons"]["STOP_LOSS_BREACHED"] == 1


def test_run_performance_analysis_success(temp_analyst_env, monkeypatch):
    state_dir, history_dir, report_file = temp_analyst_env

    mock_ai_output = {
        "summary_text": "Hasil performa CONSERVATIVE menunjukkan win rate 50% dari 2 trade.",
        "observations": ["Trade BTC untung, ETH rugi."],
        "hypotheses": ["Pola pergerakan ETH lebih volatil."],
        "suggested_investigation_areas": ["Cek trailing stop offset ETH."],
    }

    import Core.Intelligence.ai_performance_analyst as analyst_mod
    monkeypatch.setattr(analyst_mod, "_call_mistral_analyst", lambda m: mock_ai_output)

    report = run_performance_analysis(send_telegram=False)

    assert report["status"] == "SUCCESS"
    assert report_file.exists()
    assert report["ai_report"]["summary_text"] == mock_ai_output["summary_text"]

    cached = get_latest_report()
    assert cached["status"] == "SUCCESS"
    assert cached["ai_report"]["observations"] == mock_ai_output["observations"]


def test_run_performance_analysis_failsafe_fallback(temp_analyst_env, monkeypatch):
    state_dir, history_dir, report_file = temp_analyst_env

    import Core.Intelligence.ai_performance_analyst as analyst_mod
    # Simulate Mistral API failure / timeout / rate limit
    monkeypatch.setattr(analyst_mod, "_call_mistral_analyst", lambda m: None)

    report = run_performance_analysis(send_telegram=False)

    assert report["status"] == "FALLBACK_EMPTY"
    assert report_file.exists()
    assert "tidak tersedia" in report["ai_report"]["summary_text"]
    assert len(report["ai_report"]["observations"]) > 0


def test_telegram_not_sent_on_failure(temp_analyst_env, monkeypatch):
    """Verify that send_telegram=True does NOT dispatch when status != SUCCESS."""
    import Core.Intelligence.ai_performance_analyst as analyst_mod
    monkeypatch.setattr(analyst_mod, "_call_mistral_analyst", lambda m: None)

    sent_messages = []
    def mock_send(msg):
        sent_messages.append(msg)

    import Core.Support.telegram_throttle as tt_mod
    monkeypatch.setattr(tt_mod, "telegram_send", mock_send)

    report = run_performance_analysis(send_telegram=True)
    assert report["status"] == "FALLBACK_EMPTY"
    assert len(sent_messages) == 0, "Telegram message should NOT be sent when generation fails!"
