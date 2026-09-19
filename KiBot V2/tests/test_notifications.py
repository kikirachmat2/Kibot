"""
Unit tests for KiBot V2 Telegram notification system.
Tests non-blocking alert dispatch, secret safety, throttling, and risk gate triggers with mocked HTTP.
"""
import asyncio
import time
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from datetime import datetime, timezone, timedelta

from async_helper import run_async
from notifications import telegram_notifier
from notifications.telegram_notifier import TelegramNotifier
from risk.circuit_breaker import DrawdownCircuitBreaker
from risk.daily_cap import DailyLossCap
from config import settings


@run_async
async def test_notifier_dispatch_mocked():
    """Verifies that send_alert posts correct JSON payload to Telegram API."""
    notifier = TelegramNotifier(
        bot_token="test_token_12345",
        chat_id="test_chat_98765",
        global_min_interval_s=0.0,
        event_cooldown_s=0.0,
    )

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value='{"ok": true}')

    mock_post = MagicMock()
    mock_post.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_post.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession.post", return_value=mock_post) as patched_post:
        success = await notifier.send_alert(
            event_type="CIRCUIT_BREAKER_TRIPPED",
            title="🚨 TEST ALERT",
            message="Drawdown exceeded 18%",
            severity="CRITICAL",
            details={"peak": 10000000, "current": 8000000},
            force=True,
        )

        assert success is True
        assert patched_post.called
        call_kwargs = patched_post.call_args[1]
        assert "json" in call_kwargs
        payload = call_kwargs["json"]
        assert payload["chat_id"] == "test_chat_98765"
        assert "CIRCUIT_BREAKER_TRIPPED" in payload["text"]
        assert "Drawdown exceeded 18%" in payload["text"]

    await notifier.close()


@run_async
async def test_notifier_unconfigured_skips_cleanly():
    """Verifies that missing token/chat_id skips alert without throwing exceptions."""
    notifier = TelegramNotifier(bot_token="", chat_id="")
    assert not notifier.is_configured

    # Calling send_alert should return False gracefully
    res = await notifier.send_alert(
        event_type="TEST_UNCONFIGURED",
        title="Should Skip",
        message="This should not crash",
    )
    assert res is False

    # Calling non-blocking should also never throw
    notifier.send_alert_non_blocking(
        event_type="TEST_UNCONFIGURED",
        title="Should Skip",
        message="This should not crash",
    )
    await notifier.close()


@run_async
async def test_notifier_throttling():
    """Verifies that identical duplicate alerts within cooldown are throttled."""
    notifier = TelegramNotifier(
        bot_token="test_token",
        chat_id="test_chat",
        global_min_interval_s=0.0,
        event_cooldown_s=300.0,
    )

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_post = MagicMock()
    mock_post.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_post.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession.post", return_value=mock_post):
        # 1st call: goes through
        res1 = await notifier.send_alert(
            event_type="DUPLICATE_EVENT",
            title="Warning",
            message="Same error body",
            force=False,
        )
        assert res1 is True

        # 2nd call with identical event & message: throttled!
        res2 = await notifier.send_alert(
            event_type="DUPLICATE_EVENT",
            title="Warning",
            message="Same error body",
            force=False,
        )
        assert res2 is False

        # 3rd call with force=True: bypasses throttle
        res3 = await notifier.send_alert(
            event_type="DUPLICATE_EVENT",
            title="Warning",
            message="Same error body",
            force=True,
        )
        assert res3 is True

    await notifier.close()


def test_circuit_breaker_trip_triggers_alert():
    """Simulates 18% drawdown breach and confirms Telegram alert dispatch."""
    cb = DrawdownCircuitBreaker(threshold_pct=18.0)
    cb.update_equity(10_000_000.0)

    with patch.object(telegram_notifier, "send_alert_non_blocking") as mock_alert:
        # Drop equity to 8,100,000 (19% drawdown)
        safe = cb.update_equity(8_100_000.0)

        assert not safe
        assert cb.is_tripped
        assert mock_alert.called
        call_args = mock_alert.call_args[1]
        assert call_args["event_type"] == "CIRCUIT_BREAKER_TRIPPED"
        assert call_args["severity"] == "CRITICAL"


def test_daily_loss_cap_triggers_alert():
    """Simulates 3% daily loss breach and confirms Telegram alert dispatch."""
    dlc = DailyLossCap(max_loss_pct=3.0)
    dlc.update_pnl(10_000_000.0)

    with patch.object(telegram_notifier, "send_alert_non_blocking") as mock_alert:
        # Drop daily equity to 9,650,000 (3.5% loss)
        safe = dlc.update_pnl(9_650_000.0)

        assert not safe
        assert dlc.is_locked
        assert mock_alert.called
        call_args = mock_alert.call_args[1]
        assert call_args["event_type"] == "DAILY_LOSS_CAP_TRIPPED"
        assert call_args["severity"] == "HIGH"


def test_weekly_reporter_schedule_skip_logic():
    """
    Validates the 3 mock scenarios for weekly reporter baseline skip logic:
    1. First Monday baseline 00:00 WIB -> SKIP (trading just started).
    2. Tuesday 00:00 WIB -> SEND Report 1.
    3. Next Monday 00:00 WIB -> SEND Report 7 (closing week).
    """
    from notifications.weekly_reporter import WeeklyReporter
    reporter = WeeklyReporter(start_date="2026-09-21")

    # Scenario 1: First Monday 00:00 WIB (2026-09-21 00:00 WIB / 2026-09-20 17:00 UTC)
    dt_mon1 = datetime(2026, 9, 21, 0, 0, 5, tzinfo=timezone(timedelta(hours=7)))
    should_send1, reason1 = reporter.should_dispatch_report(dt_mon1)
    assert should_send1 is False
    assert "skip_first_monday_baseline" in reason1

    # Scenario 2: Tuesday 00:00 WIB (2026-09-22 00:00 WIB / 2026-09-21 17:00 UTC)
    dt_tue = datetime(2026, 9, 22, 0, 0, 5, tzinfo=timezone(timedelta(hours=7)))
    should_send2, reason2 = reporter.should_dispatch_report(dt_tue)
    assert should_send2 is True
    assert reason2 == "send_report"

    # Scenario 3: Next Monday 00:00 WIB (2026-09-28 00:00 WIB / 2026-09-27 17:00 UTC)
    dt_mon2 = datetime(2026, 9, 28, 0, 0, 5, tzinfo=timezone(timedelta(hours=7)))
    should_send3, reason3 = reporter.should_dispatch_report(dt_mon2)
    assert should_send3 is True
    assert reason3 == "send_report"

