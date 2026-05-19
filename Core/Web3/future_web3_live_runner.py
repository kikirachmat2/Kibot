from __future__ import annotations

import asyncio
import logging

from Core.Web3.future_web3_registry import FutureWeb3Registry

logger = logging.getLogger("FutureWeb3LiveRunner")


class FutureWeb3LiveRunner:
    def __init__(self) -> None:
        self.registry = FutureWeb3Registry()
        self.poll_seconds = 15

    async def tick(self):
        return self.registry.refresh()

    async def run_forever(self):
        while True:
            try:
                self.registry.refresh()
            except Exception as exc:
                logger.exception("FutureWeb3 runner failed: %s", exc)
            await asyncio.sleep(self.poll_seconds)


def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(FutureWeb3LiveRunner().run_forever())


if __name__ == "__main__":
    main()
