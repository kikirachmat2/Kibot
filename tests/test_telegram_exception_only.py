from __future__ import annotations

import inspect

from Core.Notifications.telegram_exception_notifier import TelegramExceptionNotifier


def test_telegram_exception_only_interface():
    notifier = TelegramExceptionNotifier()
    assert hasattr(notifier, "notify_exception")
    assert hasattr(notifier, "notify_trade_summary")
    src = inspect.getsource(TelegramExceptionNotifier)
    assert "dedupe" in src.lower()
    assert "cooldown" in src.lower()

