#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Support.runtime_mode_guard import assert_runtime_live_only
from Core.Treasury.live_truth_manager import LiveTruthManager
from Core.Notifications.telegram_exception_notifier import TelegramExceptionNotifier

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] LIVE-TRUTH - %(levelname)s - %(message)s")
logger = logging.getLogger("LiveTruthWriter")

_running = True


def _stop(*_args):
    global _running
    _running = False


async def main() -> None:
    assert_runtime_live_only()
    interval = float(os.getenv("KIBOT_LIVE_TRUTH_INTERVAL_S", "10") or 10)
    notifier = TelegramExceptionNotifier()
    manager = LiveTruthManager(notifier=notifier)

    logger.info("LiveTruthWriter started in LIVE_ONLY mode")
    while _running:
        try:
            payload = await manager.refresh()
            logger.info(
                "live_truth updated runtime=%s risk=%s equity=%s pnl=%s",
                payload.get("runtime_mode"),
                payload.get("risk_state"),
                payload.get("total_equity_idr") or payload.get("wallet_equity_idr"),
                payload.get("net_pnl_today_idr"),
            )
        except Exception as exc:
            logger.exception("live_truth refresh failed")
            try:
                await notifier.notify_exception(
                    event_type="LIVE_TRUTH_REFRESH_FAILED",
                    title="Live truth refresh failed",
                    message=str(exc),
                    severity="HIGH",
                )
            except Exception:
                pass
        await asyncio.sleep(interval)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    asyncio.run(main())

