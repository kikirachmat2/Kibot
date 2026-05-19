import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("Web3ExitDaemon")

ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = ROOT / "state"
POSITIONS_FILE = STATE_DIR / "web3_positions.json"
EXIT_STATE_FILE = STATE_DIR / "web3_exit_state.json"


def _read_json(path: Path, default: Any):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default


def _write_json(path: Path, payload: Any) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


class Web3ExitDaemon:
    """Refreshes open Web3 positions and applies exit discipline."""

    def __init__(self) -> None:
        self.poll_seconds = int(os.getenv("KIBOT_WEB3_EXIT_POLL_SECONDS", "30"))
        self.stale_quote_seconds = int(os.getenv("KIBOT_WEB3_QUOTE_TTL_SECONDS", "120"))
        self.max_daily_loss_pct = float(os.getenv("WEB3_DAILY_LOSS_CAP_PCT", "1.5"))
        self.default_trailing_stop_pct = float(os.getenv("WEB3_TRAILING_STOP_PCT", "0.5"))
        self.default_time_stop_seconds = int(os.getenv("WEB3_TIME_STOP_SECONDS", "1800"))

    def _load_positions(self) -> List[Dict[str, Any]]:
        payload = _read_json(POSITIONS_FILE, [])
        return payload if isinstance(payload, list) else []

    def _save_positions(self, positions: List[Dict[str, Any]]) -> None:
        _write_json(POSITIONS_FILE, positions)

    def _refresh_quote(self, position: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from Core.Web3.web3_quote_router import Web3QuoteRouter

            router = Web3QuoteRouter()
            return router.quote(
                route=str(position.get("network") or "solana"),
                input_asset=str(position.get("asset") or ""),
                output_asset="idr",
                amount_idr=float(position.get("entry_value_idr") or 0.0),
            )
        except Exception as exc:
            return {"quote_ok": False, "reason": str(exc), "expires_at": ""}

    def _should_exit(self, position: Dict[str, Any], refreshed_quote: Dict[str, Any]) -> Dict[str, Any]:
        entry_value = float(position.get("entry_value_idr") or 0.0)
        current_value = float(refreshed_quote.get("expected_out") or 0.0)
        pnl_idr = current_value - entry_value
        pnl_pct = (pnl_idr / entry_value * 100.0) if entry_value else 0.0
        opened_at = float(position.get("opened_at_ts") or position.get("opened_at") or time.time())
        age_seconds = max(0.0, time.time() - opened_at)
        trailing_stop_pct = float(position.get("trailing_stop_pct") or self.default_trailing_stop_pct)
        time_stop_seconds = int(position.get("time_stop_seconds") or self.default_time_stop_seconds)
        stop_loss_pct = float(position.get("stop_loss_pct") or 0.0)
        take_profit_pct = float(position.get("take_profit_pct") or 0.0)

        reason = ""
        action = "HOLD"
        if not refreshed_quote.get("quote_ok"):
            reason = "stale_quote"
            action = "EXIT"
        elif take_profit_pct > 0 and pnl_pct >= take_profit_pct:
            reason = "take_profit"
            action = "EXIT"
        elif stop_loss_pct > 0 and pnl_pct <= -abs(stop_loss_pct):
            reason = "stop_loss"
            action = "EXIT"
        elif pnl_pct > trailing_stop_pct and current_value < entry_value * (1 + (pnl_pct - trailing_stop_pct) / 100.0):
            reason = "trailing_stop"
            action = "EXIT"
        elif time_stop_seconds > 0 and age_seconds >= time_stop_seconds:
            reason = "time_stop"
            action = "EXIT"

        return {
            "action": action,
            "reason": reason,
            "pnl_idr": pnl_idr,
            "pnl_pct": pnl_pct,
            "age_seconds": age_seconds,
        }

    def tick(self) -> Dict[str, Any]:
        positions = self._load_positions()
        refreshed = []
        summary = {"open": 0, "closed": 0, "blocked": 0, "exits": []}
        for position in positions:
            if str(position.get("status") or "").upper() != "OPEN":
                refreshed.append(position)
                continue
            quote = self._refresh_quote(position)
            decision = self._should_exit(position, quote)
            position["last_exit_check_at"] = datetime.now(timezone.utc).isoformat()
            position["last_quote"] = quote
            position["last_exit_decision"] = decision
            if decision["action"] == "EXIT":
                position["status"] = "CLOSED"
                position["closed_at"] = position["last_exit_check_at"]
                summary["closed"] += 1
                summary["exits"].append({"id": position.get("id"), "reason": decision["reason"], "pnl_pct": decision["pnl_pct"]})
            else:
                summary["open"] += 1
            refreshed.append(position)

        self._save_positions(refreshed)
        state = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "poll_seconds": self.poll_seconds,
            "status": "OK",
            "positions_open": summary["open"],
            "positions_closed": summary["closed"],
            "positions_blocked": summary["blocked"],
            "exits": summary["exits"][:20],
        }
        _write_json(EXIT_STATE_FILE, state)
        return state

    def run_forever(self) -> None:
        logger.info("Web3 exit daemon starting.")
        while True:
            try:
                self.tick()
            except Exception as exc:
                logger.exception("Web3 exit daemon tick failed: %s", exc)
            time.sleep(self.poll_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    Web3ExitDaemon().run_forever()


if __name__ == "__main__":
    main()
