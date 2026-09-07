"""Unit tests for Live Trading Readiness Evaluator."""

import json
from pathlib import Path
import pytest
from unittest.mock import patch

from Core.Intelligence.live_readiness import (
    evaluate_approved_readiness,
    format_readiness_scorecard,
    check_and_notify_milestones,
    TARGET_SAMPLE_SIZE,
    TARGET_PROFIT_FACTOR,
    TARGET_WIN_RATE_PCT,
    MAX_DRAWDOWN_LIMIT_PCT,
    TARGET_CALENDAR_DAYS,
)


@pytest.fixture
def mock_readiness_env(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    trade_history_dir = state_dir / "trade_history"
    trade_history_dir.mkdir(parents=True, exist_ok=True)
    equity_file = state_dir / "paper_equity_approved.json"
    milestone_file = state_dir / "readiness_milestones.json"

    import Core.Intelligence.live_readiness as lr_mod
    monkeypatch.setattr(lr_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(lr_mod, "TRADE_HISTORY_DIR", trade_history_dir)
    monkeypatch.setattr(lr_mod, "PAPER_EQUITY_APPROVED_FILE", equity_file)
    monkeypatch.setattr(lr_mod, "READINESS_STATE_FILE", milestone_file)

    return state_dir, trade_history_dir, equity_file, milestone_file


def _write_approved_trades(trade_history_dir: Path, trades_spec: list):
    lines = []
    for t in trades_spec:
        row = {
            "status": "CLOSED",
            "variant_id": "APPROVED",
            "pair": t.get("pair", "BTC/IDR"),
            "realized_pnl_idr": t["pnl_idr"],
            "realized_pnl_pct": t.get("pnl_pct", 1.0 if t["pnl_idr"] > 0 else -1.0),
            "date_wib": t.get("date_wib", "2026-09-01"),
        }
        lines.append(json.dumps(row))
    (trade_history_dir / "paper_approved.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_readiness_insufficient_sample(mock_readiness_env):
    state_dir, history_dir, eq_file, _ = mock_readiness_env
    eq_file.write_text(json.dumps({
        "initial_bankroll_idr": 5000000.0,
        "current_equity_idr": 4997950.0,
        "overall_drawdown_pct": 0.12,
    }), encoding="utf-8")

    # 7 trades: 3 wins (+30,000 IDR), 4 losses (-32,050 IDR) across 2 days
    trades = [
        {"pnl_idr": 10000.0, "date_wib": "2026-09-06"},
        {"pnl_idr": 10000.0, "date_wib": "2026-09-06"},
        {"pnl_idr": 10000.0, "date_wib": "2026-09-07"},
        {"pnl_idr": -8000.0, "date_wib": "2026-09-06"},
        {"pnl_idr": -8000.0, "date_wib": "2026-09-06"},
        {"pnl_idr": -8000.0, "date_wib": "2026-09-07"},
        {"pnl_idr": -8050.0, "date_wib": "2026-09-07"},
    ]
    _write_approved_trades(history_dir, trades)

    eval_res = evaluate_approved_readiness()
    assert eval_res["all_passed"] is False
    assert eval_res["verdict"] == "BELUM_SIAP"
    assert eval_res["metrics"]["total_trades"] == 7
    assert eval_res["metrics"]["calendar_days_count"] == 2
    assert eval_res["criteria"]["sample_size"]["passed"] is False
    assert eval_res["criteria"]["calendar_days"]["passed"] is False

    card = format_readiness_scorecard(eval_res)
    assert "BELUM SIAP" in card
    assert "7/30" in card


def test_readiness_fails_if_days_under_10(mock_readiness_env):
    """N >= 30 and good PF/WR, but clustered in only 4 calendar days -> MUST FAIL."""
    state_dir, history_dir, eq_file, _ = mock_readiness_env
    eq_file.write_text(json.dumps({
        "initial_bankroll_idr": 5000000.0,
        "current_equity_idr": 5200000.0,
        "overall_drawdown_pct": 1.5,
    }), encoding="utf-8")

    # 30 trades (18 wins, 12 losses) but only across 4 days
    trades = []
    for i in range(30):
        day = f"2026-09-0{1 + (i % 4)}"
        pnl = 15000.0 if i < 18 else -8000.0
        trades.append({"pnl_idr": pnl, "date_wib": day})
    _write_approved_trades(history_dir, trades)

    eval_res = evaluate_approved_readiness()
    assert eval_res["metrics"]["total_trades"] == 30
    assert eval_res["criteria"]["sample_size"]["passed"] is True
    assert eval_res["criteria"]["profit_factor"]["passed"] is True
    assert eval_res["criteria"]["calendar_days"]["passed"] is False  # 4 < 10
    assert eval_res["verdict"] == "BELUM_SIAP"
    assert eval_res["all_passed"] is False


def test_readiness_passes_all_5_criteria_unlocks_soft_launch(mock_readiness_env):
    """All 5 criteria met -> verdict is SIAP_SOFT_LAUNCH."""
    state_dir, history_dir, eq_file, _ = mock_readiness_env
    eq_file.write_text(json.dumps({
        "initial_bankroll_idr": 5000000.0,
        "current_equity_idr": 5300000.0,
        "overall_drawdown_pct": 2.1,
    }), encoding="utf-8")

    # 32 trades: 18 wins (+15,000 IDR), 14 losses (-6,000 IDR) across 12 distinct days
    # PF = (18 * 15,000) / (14 * 6,000) = 270,000 / 84,000 = 3.21 >= 1.50
    # WR = 18 / 32 = 56.25% >= 45.0%
    # DD = 2.1% <= 6.0%
    # Days = 12 >= 10
    trades = []
    for i in range(32):
        day_num = 1 + (i % 12)
        day_str = f"2026-09-{day_num:02d}"
        pnl = 15000.0 if i < 18 else -6000.0
        trades.append({"pnl_idr": pnl, "date_wib": day_str})
    _write_approved_trades(history_dir, trades)

    eval_res = evaluate_approved_readiness()
    assert eval_res["all_passed"] is True
    assert eval_res["verdict"] == "SIAP_SOFT_LAUNCH"
    assert eval_res["verdict_badge"] == "🟡"
    assert "SIAP SOFT LAUNCH" in eval_res["verdict_title"]

    card = format_readiness_scorecard(eval_res)
    assert "SIAP SOFT LAUNCH" in card
    assert "MODAL MIKRO" in card


def test_milestone_and_transition_alerts(mock_readiness_env):
    state_dir, history_dir, eq_file, ms_file = mock_readiness_env
    eq_file.write_text(json.dumps({
        "initial_bankroll_idr": 5000000.0,
        "current_equity_idr": 5000000.0,
        "overall_drawdown_pct": 0.0,
    }), encoding="utf-8")

    # Start with 9 trades -> no alert
    trades_9 = [{"pnl_idr": 5000.0, "date_wib": f"2026-09-0{i+1}"} for i in range(9)]
    _write_approved_trades(history_dir, trades_9)
    res9 = evaluate_approved_readiness()
    alert9 = check_and_notify_milestones(res9, send_telegram=False)
    assert alert9["alert_sent"] is False

    # Add 1 trade -> reaches N=10 milestone!
    trades_10 = trades_9 + [{"pnl_idr": 5000.0, "date_wib": "2026-09-10"}]
    _write_approved_trades(history_dir, trades_10)
    res10 = evaluate_approved_readiness()
    alert10 = check_and_notify_milestones(res10, send_telegram=False)
    assert alert10["alert_sent"] is True
    assert alert10["incident_key"] == "READINESS_MILESTONE_10"

    # Subsequent check at N=10 does NOT send duplicate
    alert10_dup = check_and_notify_milestones(res10, send_telegram=False)
    assert alert10_dup["alert_sent"] is False
