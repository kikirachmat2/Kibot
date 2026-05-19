from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from Core.Scanner.scanner_health import write_scanner_health

logger = logging.getLogger("ScannerHealthRunner")
STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"


async def run_forever() -> None:
    while True:
        try:
            write_scanner_health({})
        except Exception as exc:  # pragma: no cover
            logger.exception("scanner health refresh failed: %s", exc)
        await asyncio.sleep(30)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
