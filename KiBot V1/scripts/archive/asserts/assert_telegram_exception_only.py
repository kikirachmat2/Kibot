#!/usr/bin/env python3
from __future__ import annotations

import inspect
import os

from Core.Notifications.telegram_exception_notifier import TelegramExceptionNotifier


def main() -> int:
    notifier = TelegramExceptionNotifier()
    if not hasattr(notifier, "notify_exception"):
        print("FAIL:notify_exception_missing")
        return 1
    if not hasattr(notifier, "notify_trade_summary"):
        print("FAIL:notify_trade_summary_missing")
        return 1
    if "dedupe" not in inspect.getsource(TelegramExceptionNotifier):
        print("FAIL:dedupe_missing")
        return 1
    if "cooldown" not in inspect.getsource(TelegramExceptionNotifier):
        print("FAIL:cooldown_missing")
        return 1
    token = os.getenv("KIBOT_TELEGRAM_TOKEN")
    chat = os.getenv("KIBOT_TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("OK:TELEGRAM_EXCEPTION_ONLY_MISSING_TOKEN_DISABLED")
        return 0
    print("OK:TELEGRAM_EXCEPTION_ONLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

