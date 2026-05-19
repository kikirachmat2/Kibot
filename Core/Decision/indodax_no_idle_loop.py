from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from Core.Scanner.indodax_market_scanner import IndodaxMarketScanner
from Core.Decision.deadline_profit_enforcer import DeadlineProfitEnforcer
from Core.Decision.engine_independence import write_engine_independence

logger = logging.getLogger("IndodaxNoIdleLoop")
STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "indodax_no_idle.json"


class IndodaxNoIdleLoop:
    def __init__(self) -> None:
        self.scanner = IndodaxMarketScanner()
        self.enforcer = DeadlineProfitEnforcer()
        self.poll_seconds = 8

    def _write_state(self, payload: Dict[str, Any]) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    async def tick(self) -> Dict[str, Any]:
        scan = await self.scanner.scan()
        candidates = scan.get("candidates", []) if isinstance(scan, dict) else []
        best = scan.get("best_candidate", {}) if isinstance(scan, dict) else {}
        pnl_pct = float(scan.get("daily_pnl_pct", 0.0) or 0.0) if isinstance(scan, dict) else 0.0
        pnl_idr = float(scan.get("daily_pnl_idr", 0.0) or 0.0) if isinstance(scan, dict) else 0.0
        deadline = self.enforcer.evaluate_enforcer(pnl_pct, pnl_idr, 1416) if hasattr(self.enforcer, "evaluate_enforcer") else {}
        governor = {}
        gov_path = STATE_DIR / "capital_governor.json"
        if gov_path.exists():
            try:
                governor = json.loads(gov_path.read_text(encoding="utf-8"))
            except Exception:
                governor = {}
        indodax_state = ((governor.get("venues", {}) or {}).get("indodax", {}) if isinstance(governor, dict) else {})
        indodax_allow = bool(indodax_state.get("allow_orders", scan.get("source_status") == "OK"))
        indodax_reason = str(indodax_state.get("reason") or scan.get("no_data_reason") or "")
        posture = "ACTIVE_SEARCHING" if candidates else "ACTIVE_SEARCHING"
        reason = best.get("reason") if isinstance(best, dict) else ""
        state = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "posture": posture,
            "best_candidate": best,
            "why_not_trading": reason or scan.get("no_data_reason") or "no_candidate_passed_source_proof_or_momentum",
            "next_action": "SCAN_NEXT",
            "next_check_seconds": self.poll_seconds,
            "pairs_checked": int(scan.get("pairs_checked", 0) or 0),
            "approved_candidates": int(len(scan.get("approved_candidates", []) or [])),
            "rejected_candidates": int(len(scan.get("rejected_candidates", []) or [])),
            "deadline": deadline,
        }
        self._write_state(state)
        write_engine_independence({
            "indodax_engine": {
                "status": "ACTIVE" if scan.get("source_status") == "OK" and indodax_allow else "BLOCKED_WITH_REASON",
                "scanner": "ACTIVE" if scan.get("source_status") == "OK" else "BLOCKED_WITH_REASON",
                "executor": "ACTIVE" if indodax_allow else "BLOCKED_WITH_REASON",
                "allow_orders": indodax_allow,
                "reason": indodax_reason,
            }
        })
        return state

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                logger.exception("Indodax no-idle loop failed: %s", exc)
            await asyncio.sleep(self.poll_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(IndodaxNoIdleLoop().run_forever())


if __name__ == "__main__":
    main()
