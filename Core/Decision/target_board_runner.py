from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from Core.Decision.indodax_target_board import build_indodax_target_board
from Core.Decision.phantom_target_board import build_phantom_target_board
from Core.Treasury.phantom_capital_mover import write_phantom_capital_mover
from Core.Treasury.phantom_network_maximizer import write_phantom_network_maximizer
from Core.Decision.engine_independence import write_engine_independence

logger = logging.getLogger("TargetBoardRunner")
STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "target_board_runtime.json"


def _write_runtime(indodax: dict, phantom: dict, error: str = "") -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "loop_interval_seconds": 5,
        "indodax_updated": bool(indodax),
        "phantom_updated": bool(phantom),
        "indodax_count": len(indodax.get("top_targets", []) or []),
        "phantom_count": len(phantom.get("top_targets", []) or []),
        "errors": {"last_error": error} if error else {},
    }
    STATE_FILE.write_text(__import__("json").dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


async def run_forever() -> None:
    while True:
        try:
            indo = build_indodax_target_board()
            ph = build_phantom_target_board()
            write_phantom_capital_mover({})
            write_phantom_network_maximizer({})
            write_engine_independence({})
            _write_runtime(indo, ph, "")
        except Exception as exc:  # pragma: no cover
            logger.exception("target board refresh failed: %s", exc)
            _write_runtime({}, {}, str(exc))
        await asyncio.sleep(5)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
