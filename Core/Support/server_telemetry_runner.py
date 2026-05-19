from __future__ import annotations

import asyncio
import logging

from Core.Support.server_telemetry import write_server_telemetry

logger = logging.getLogger("ServerTelemetryRunner")


async def run_forever() -> None:
    while True:
        try:
            write_server_telemetry({})
        except Exception as exc:  # pragma: no cover
            logger.exception("server telemetry refresh failed: %s", exc)
        await asyncio.sleep(5)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
