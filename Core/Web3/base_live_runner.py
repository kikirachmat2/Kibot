from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from Core.Web3.base_position_manager import BasePositionManager
from Core.Web3.base_swap_executor import BaseSwapExecutor

logger = logging.getLogger("BaseLiveRunner")
ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = ROOT / "state"


class BaseLiveRunner:
    def __init__(self) -> None:
        self.executor = BaseSwapExecutor()
        self.positions = BasePositionManager()
        self.poll_seconds = float(__import__("os").getenv("BASE_POLL_SECONDS", "10") or 10)

    async def tick(self) -> dict:
        status = self.executor.readiness()
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        (STATE_DIR / "base_quote_state.json").write_text(json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "status": status["status"], "reason": status["reason"]}, indent=2))
        return status

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                logger.exception("Base runner tick failed: %s", exc)
            await asyncio.sleep(self.poll_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(BaseLiveRunner().run_forever())


if __name__ == "__main__":
    main()
