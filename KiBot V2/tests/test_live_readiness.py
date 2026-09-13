"""
Unit tests for LiveReadinessEvaluator (KiBot V2).
Tests the 5 canonical criteria ported from V1 live_readiness.py using synthetic datasets:
1. Sample Size (>= 30 trades)
2. Profit Factor (>= 1.50)
3. Net Win Rate (>= 45.0%)
4. Max Drawdown (<= 6.0%)
5. Time Diversity (>= 10 calendar days)

Also validates milestone alerts and verifies the read-only guarantee for LIVE_TRADING_ENABLED.
"""
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest

from storage.live_readiness import LiveReadinessEvaluator
from notifications import telegram_notifier
from config import settings

WIB = timezone(timedelta(hours=7))


def generate_synthetic_trades(
    count: int = 35,
    win_rate: float = 0.60,
    avg_win_idr: float = 30_000.0,
    avg_loss_idr: float = 10_000.0,
    num_days: int = 12,
):
    """Generates synthetic closed trade records spanning multiple calendar days."""
    trades = []
    base_time = datetime(2026, 9, 1, 10, 0, 0, tzinfo=WIB).timestamp()

    for i in range(count):
        day_offset = (i % num_days) * 86400
        trade_ts = base_time + day_offset + (i * 120)
        is_win = (i / count) < win_rate

        if is_win:
            pnl_idr = avg_win_idr
            pnl_pct = 2.5
        else:
            pnl_idr = -avg_loss_idr
            pnl_pct = -1.5

        trades.append({
            "position_id": f"pos_{i}",
            "symbol": "BTC/IDR",
            "entry_price": 1_000_000_000.0,
            "exit_price": 1_025_000_000.0 if is_win else 985_000_000.0,
            "amount_coins": 0.001,
            "cost_idr": 1_000_000.0,
            "realized_pnl_idr": pnl_idr,
            "realized_pnl_pct": pnl_pct,
            "exit_time": trade_ts,
            "exit_reason": "TAKE_PROFIT_TARGET_HIT" if is_win else "STOP_LOSS_BREACHED",
        })
    return trades


def test_evaluator_all_passed():
    """Dataset with 35 trades, 60% win rate, PF 3.0, 12 days, 2% DD -> SIAP_SOFT_LAUNCH."""
    evaluator = LiveReadinessEvaluator()
    trades = generate_synthetic_trades(count=35, win_rate=0.60, avg_win_idr=30_000, avg_loss_idr=10_000, num_days=12)

    res = evaluator.evaluate_trades(
        trade_history=trades,
        current_equity_idr=10_500_000.0,
        initial_bankroll_idr=10_000_000.0,
        peak_equity_idr=10_600_000.0,
        current_drawdown_pct=0.94,
    )

    assert res["verdict"] == "SIAP_SOFT_LAUNCH"
    assert res["all_passed"] is True
    assert res["criteria"]["sample_size"]["passed"] is True
    assert res["criteria"]["profit_factor"]["passed"] is True
    assert res["criteria"]["win_rate"]["passed"] is True
    assert res["criteria"]["max_drawdown"]["passed"] is True
    assert res["criteria"]["calendar_days"]["passed"] is True


def test_evaluator_fails_sample_size():
    """Fails if trades < 30."""
    evaluator = LiveReadinessEvaluator()
    trades = generate_synthetic_trades(count=20, win_rate=0.70, num_days=12)

    res = evaluator.evaluate_trades(
        trade_history=trades,
        current_drawdown_pct=2.0,
    )

    assert res["verdict"] == "BELUM_SIAP"
    assert res["all_passed"] is False
    assert res["criteria"]["sample_size"]["passed"] is False
    assert "Sample trade 20/30" in res["verdict_title"]


def test_evaluator_fails_profit_factor():
    """Fails if Profit Factor < 1.50."""
    evaluator = LiveReadinessEvaluator()
    # High losses, low wins
    trades = generate_synthetic_trades(count=35, win_rate=0.50, avg_win_idr=10_000, avg_loss_idr=20_000, num_days=12)

    res = evaluator.evaluate_trades(
        trade_history=trades,
        current_drawdown_pct=2.0,
    )

    assert res["verdict"] == "BELUM_SIAP"
    assert res["all_passed"] is False
    assert res["criteria"]["profit_factor"]["passed"] is False


def test_evaluator_fails_win_rate():
    """Fails if Win Rate < 45.0%."""
    evaluator = LiveReadinessEvaluator()
    trades = generate_synthetic_trades(count=40, win_rate=0.35, avg_win_idr=50_000, avg_loss_idr=10_000, num_days=12)

    res = evaluator.evaluate_trades(
        trade_history=trades,
        current_drawdown_pct=3.0,
    )

    assert res["verdict"] == "BELUM_SIAP"
    assert res["all_passed"] is False
    assert res["criteria"]["win_rate"]["passed"] is False


def test_evaluator_fails_max_drawdown():
    """Fails if Max Drawdown > 6.0%."""
    evaluator = LiveReadinessEvaluator()
    trades = generate_synthetic_trades(count=35, win_rate=0.60, num_days=12)

    res = evaluator.evaluate_trades(
        trade_history=trades,
        current_drawdown_pct=7.5,  # Exceeds 6.0% limit
    )

    assert res["verdict"] == "BELUM_SIAP"
    assert res["all_passed"] is False
    assert res["criteria"]["max_drawdown"]["passed"] is False


def test_evaluator_fails_calendar_days():
    """Fails if trades occur on < 10 distinct calendar days."""
    evaluator = LiveReadinessEvaluator()
    # 35 trades all within 3 days
    trades = generate_synthetic_trades(count=35, win_rate=0.60, num_days=3)

    res = evaluator.evaluate_trades(
        trade_history=trades,
        current_drawdown_pct=2.0,
    )

    assert res["verdict"] == "BELUM_SIAP"
    assert res["all_passed"] is False
    assert res["criteria"]["calendar_days"]["passed"] is False


def test_milestone_notification_trigger():
    """Verifies that reaching 10, 20, 30 trades dispatches non-blocking Telegram alerts."""
    evaluator = LiveReadinessEvaluator()

    with patch.object(telegram_notifier, "send_alert_non_blocking") as mock_alert:
        trades_10 = generate_synthetic_trades(count=10, num_days=5)
        evaluator.evaluate_trades(trade_history=trades_10)

        assert mock_alert.called
        event_types = [c[1]["event_type"] for c in mock_alert.call_args_list]
        assert "READINESS_MILESTONE" in event_types
        assert evaluator.last_milestone_notified == 10


def test_live_trading_enabled_remains_false():
    """
    CRITICAL READ-ONLY SAFETY TEST:
    Proves that even when all 5 criteria pass and verdict is SIAP_SOFT_LAUNCH,
    LIVE_TRADING_ENABLED in config/settings is NEVER modified automatically.
    """
    assert settings.LIVE_TRADING_ENABLED is False

    evaluator = LiveReadinessEvaluator()
    trades_perfect = generate_synthetic_trades(count=40, win_rate=0.65, avg_win_idr=30_000, avg_loss_idr=10_000, num_days=15)
    res = evaluator.evaluate_trades(
        trade_history=trades_perfect,
        current_equity_idr=11_000_000.0,
        peak_equity_idr=11_000_000.0,
        current_drawdown_pct=0.0,
    )

    assert res["verdict"] == "SIAP_SOFT_LAUNCH"
    assert settings.LIVE_TRADING_ENABLED is False, "CRITICAL ERROR: LIVE_TRADING_ENABLED was mutated automatically!"
