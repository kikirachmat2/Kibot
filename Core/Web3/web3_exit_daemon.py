import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from Core.Web3.web3_quote_router import Web3QuoteRouter

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
    """Refreshes open Web3 positions and emits exit recommendations safely."""

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

    async def _refresh_quote(self, position: Dict[str, Any]) -> Dict[str, Any]:
        try:
            router = Web3QuoteRouter()
            amount_raw = int(position.get("amount_raw") or position.get("amount") or 0)
            if amount_raw <= 0:
                return {
                    "quote_ok": False,
                    "reason": "quote_context_missing",
                    "expected_out": 0,
                    "expires_at": None,
                }
            return await router.quote(
                route=str(position.get("network") or "solana"),
                input_asset=str(position.get("input_asset") or position.get("asset") or ""),
                output_asset=str(position.get("output_asset") or "So11111111111111111111111111111111111111112"),
                amount_raw=amount_raw,
                trade_size_idr=float(position.get("entry_value_idr") or position.get("current_value_idr") or 0.0),
                balance_snapshot={"position": position},
                route_context={"source": "web3_exit_daemon", "position_id": position.get("id")},
            )
        except Exception as exc:
            return {"quote_ok": False, "reason": str(exc), "expires_at": None, "expected_out": 0}

    def _should_recommend_exit(self, position: Dict[str, Any], refreshed_quote: Dict[str, Any]) -> Dict[str, Any]:
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
        fee_state = refreshed_quote.get("fee_intelligence") if isinstance(refreshed_quote.get("fee_intelligence"), dict) else {}
        gas_reason = str((fee_state or {}).get("gas_reason") or refreshed_quote.get("gas_reason") or "").strip()

        reason = ""
        action = "HOLD"
        if not refreshed_quote.get("quote_ok"):
            reason = refreshed_quote.get("reason") or "stale_quote"
            action = "EXIT_RECOMMENDED"
        elif fee_state and not bool(fee_state.get("gas_affordable", True)):
            reason = gas_reason or "gas_fee_unaffordable"
            action = "EXIT_RECOMMENDED"
        elif take_profit_pct > 0 and pnl_pct >= take_profit_pct:
            reason = "take_profit"
            action = "EXIT_RECOMMENDED"
        elif stop_loss_pct > 0 and pnl_pct <= -abs(stop_loss_pct):
            reason = "stop_loss"
            action = "EXIT_RECOMMENDED"
        elif pnl_pct > trailing_stop_pct and current_value < entry_value * (1 + (pnl_pct - trailing_stop_pct) / 100.0):
            reason = "trailing_stop"
            action = "EXIT_RECOMMENDED"
        elif time_stop_seconds > 0 and age_seconds >= time_stop_seconds:
            reason = "time_stop"
            action = "EXIT_RECOMMENDED"

        return {
            "action": action,
            "reason": reason,
            "pnl_idr": pnl_idr,
            "pnl_pct": pnl_pct,
            "age_seconds": age_seconds,
            "needs_operator_attention": action == "EXIT_RECOMMENDED" and (not refreshed_quote.get("quote_ok") or bool(fee_state and not fee_state.get("gas_affordable", True))),
        }

    async def tick_async(self) -> Dict[str, Any]:
        positions = self._load_positions()
        refreshed = []
        summary = {"open": 0, "recommended": 0, "blocked": 0, "closed": 0, "exits": []}

        for position in positions:
            status = str(position.get("status") or "").upper()
            if status in {"CLOSED", "EXIT_SUBMITTED"}:
                refreshed.append(position)
                continue

            quote = self._refresh_quote(position)
            if asyncio.iscoroutine(quote):
                quote = await quote
            decision = self._should_recommend_exit(position, quote)
            position["last_exit_check_at"] = datetime.now(timezone.utc).isoformat()
            position["last_quote"] = quote
            position["last_exit_decision"] = decision

            if decision["action"] == "EXIT_RECOMMENDED":
                position["status"] = "EXIT_RECOMMENDED"
                position["exit_recommended"] = True
                position["exit_reason"] = decision["reason"]
                position["needs_operator_attention"] = bool(decision.get("needs_operator_attention"))
                summary["recommended"] += 1
                summary["exits"].append({
                    "id": position.get("id"),
                    "reason": decision["reason"],
                    "pnl_pct": decision["pnl_pct"],
                })
            else:
                position["status"] = "OPEN"
                position["exit_recommended"] = False
                position["needs_operator_attention"] = False
                summary["open"] += 1

            refreshed.append(position)

        self._save_positions(refreshed)
        latest_exit_reason = summary["exits"][0]["reason"] if summary["exits"] else ""
        state = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "poll_seconds": self.poll_seconds,
            "status": "OK" if not summary["blocked"] else "BLOCKED",
            "positions_open": summary["open"],
            "positions_closed": summary["closed"],
            "positions_blocked": summary["blocked"],
            "positions_recommended": summary["recommended"],
            "latest_exit_reason": latest_exit_reason,
            "exits": summary["exits"][:20],
        }
        _write_json(EXIT_STATE_FILE, state)
        return state

    def tick(self) -> Dict[str, Any]:
        return asyncio.run(self.tick_async())

    async def run_forever_async(self) -> None:
        logger.info("Web3 exit daemon starting.")
        while True:
            try:
                await self.tick_async()
            except Exception as exc:
                logger.exception("Web3 exit daemon tick failed: %s", exc)
            await asyncio.sleep(self.poll_seconds)

    def run_forever(self) -> None:
        asyncio.run(self.run_forever_async())


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    Web3ExitDaemon().run_forever()


if __name__ == "__main__":
    main()
