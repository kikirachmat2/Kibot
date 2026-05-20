from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from Core.Support.ki_config import STATE_DIR
from Core.Treasury.capital_governor import CapitalGovernor, GOVERNOR_FILE, load_daily_inventory_snapshot
from Core.sovereign_state import load_strategy, save_strategy

logger = logging.getLogger("KiBot.DailyResetCoordinator")

WIB = timezone(timedelta(hours=int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7"))))
STATE_FILE = STATE_DIR / "daily_reset_state.json"
DEFAULT_POLL_SECONDS = float(os.getenv("KIBOT_DAILY_RESET_POLL_SECONDS", "5") or 5)
DEFAULT_PRE_CLOSE_MINUTES = int(os.getenv("KIBOT_DAILY_RESET_PRE_CLOSE_MINUTES", "15") or 15)


def _now_wib() -> datetime:
    return datetime.now(WIB)


def _minutes_to_midnight_wib(now: datetime | None = None) -> int:
    now = now or _now_wib()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return max(0, int((midnight - now).total_seconds() // 60))


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("Failed to read %s: %s", path, exc)
    return default


def _write_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    resolved = {
        "updated_at": _now_wib().isoformat(),
        "wib_date": str(_now_wib().date()),
        "status": "IDLE",
        "minutes_to_midnight": _minutes_to_midnight_wib(),
        "pre_close_minutes": DEFAULT_PRE_CLOSE_MINUTES,
        "previous_global_mode": "",
        "current_global_mode": "",
        "forced_exit_all": False,
        "inventory_open_count": 0,
        "inventory_open_symbols": [],
        "governor_date": "",
        "governor_anchor_date": "",
        "daily_anchor_status": "",
        "reason": "",
        "next_action": "MONITOR",
        "next_check_seconds": DEFAULT_POLL_SECONDS,
    }
    resolved.update(payload or {})
    STATE_FILE.write_text(json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")
    return resolved


def _snapshot_previous_strategy(current_strategy: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    previous = dict(current_strategy or {})
    previous_mode = str(previous.get("global_mode") or state.get("previous_global_mode") or "").upper().strip()
    if not previous_mode or previous_mode == "EXIT_ALL":
        previous_mode = "LIVE_AUTONOMOUS_TRADING"
    state["previous_strategy"] = previous
    state["previous_global_mode"] = previous_mode
    return state


async def evaluate_daily_reset() -> Dict[str, Any]:
    now = _now_wib()
    today = str(now.date())
    minutes_to_midnight = _minutes_to_midnight_wib(now)
    pre_close_window = minutes_to_midnight <= DEFAULT_PRE_CLOSE_MINUTES

    strategy = load_strategy()
    current_mode = str(strategy.get("global_mode") or "UNKNOWN").upper().strip()
    inventory = load_daily_inventory_snapshot()
    governor_data = _read_json(GOVERNOR_FILE, {})
    governor_date = str(governor_data.get("date") or "").strip()
    governor_pending = bool(governor_data.get("daily_reset_pending", False))
    current_equity = float(
        governor_data.get("current_total_equity_idr")
        or governor_data.get("current_equity_idr")
        or 0.0
    )

    state = _read_json(STATE_FILE, {})
    if not isinstance(state, dict):
        state = {}

    has_open_inventory = bool(inventory.get("has_open_inventory"))
    inventory_count = int(inventory.get("open_count", 0) or 0)
    inventory_symbols = list(inventory.get("open_symbols", []) or [])
    day_changed = bool(governor_date and governor_date != today)
    rollover_active = pre_close_window or governor_pending or day_changed or has_open_inventory
    daily_exit_owned = bool(state.get("forced_exit_all", False) or state.get("previous_strategy"))

    if rollover_active and current_mode != "EXIT_ALL":
        state = _snapshot_previous_strategy(strategy, state)
        exit_strategy = dict(strategy or {})
        exit_strategy["global_mode"] = "EXIT_ALL"
        daily_state = exit_strategy.get("daily_state")
        if not isinstance(daily_state, dict):
            daily_state = {}
        daily_state.setdefault("color", "RECOVERY")
        daily_state["reason"] = "daily_rollover_exit_pending"
        daily_state["deadline_mode"] = "EXIT_ALL"
        exit_strategy["daily_state"] = daily_state
        save_strategy(exit_strategy)
        current_mode = "EXIT_ALL"

    governor = CapitalGovernor(None, None)
    governor.current_total_equity_idr = current_equity
    if rollover_active or governor_pending or day_changed:
        await governor.check_daily_reset(current_equity)

    refreshed_governor = _read_json(GOVERNOR_FILE, {})
    governor_date = str(refreshed_governor.get("date") or governor_date or "").strip()
    governor_pending = bool(refreshed_governor.get("daily_reset_pending", False))
    allow_new_orders = bool(refreshed_governor.get("allow_new_orders", False))
    allow_reason = str(refreshed_governor.get("allow_new_orders_reason") or "").strip()
    has_previous_strategy = bool(isinstance(state.get("previous_strategy"), dict) and state.get("previous_strategy"))
    daily_exit_owned = bool(daily_exit_owned or state.get("forced_exit_all", False))

    restore_required = bool(
        rollover_active
        or governor_pending
        or day_changed
        or daily_exit_owned
        or has_previous_strategy
    )

    if restore_required and not has_open_inventory and not governor_pending and governor_date == today:
        restore_strategy = state.get("previous_strategy") if isinstance(state.get("previous_strategy"), dict) else {}
        restore_mode = str(state.get("previous_global_mode") or restore_strategy.get("global_mode") or "").upper().strip()
        if not restore_mode or restore_mode == "EXIT_ALL":
            restore_mode = "LIVE_AUTONOMOUS_TRADING"
        if restore_strategy:
            restore = dict(restore_strategy)
            restore["global_mode"] = restore_mode
        else:
            restore = dict(strategy or {})
            restore["global_mode"] = restore_mode
        save_strategy(restore)
        current_mode = restore_mode
        state.pop("previous_strategy", None)
        state = _write_state({
            "status": "RESET_DONE",
            "minutes_to_midnight": minutes_to_midnight,
            "pre_close_minutes": DEFAULT_PRE_CLOSE_MINUTES,
            "previous_global_mode": restore_mode,
            "current_global_mode": current_mode,
            "forced_exit_all": False,
            "inventory_open_count": 0,
            "inventory_open_symbols": [],
            "governor_date": governor_date,
            "governor_anchor_date": governor_date,
            "daily_anchor_status": "RESET_DONE",
            "reason": "daily_anchor_reset_complete",
            "next_action": "MONITOR",
            "next_check_seconds": DEFAULT_POLL_SECONDS,
            "previous_strategy": {},
        })
        return state

    if not restore_required:
        monitoring_status = "MONITORING"
        monitoring_reason = "external_exit_all_active" if current_mode == "EXIT_ALL" else "monitoring"
        return _write_state({
            "status": monitoring_status,
            "minutes_to_midnight": minutes_to_midnight,
            "pre_close_minutes": DEFAULT_PRE_CLOSE_MINUTES,
            "previous_global_mode": str(state.get("previous_global_mode") or current_mode or ""),
            "current_global_mode": current_mode,
            "forced_exit_all": bool(state.get("forced_exit_all", False)),
            "inventory_open_count": inventory_count,
            "inventory_open_symbols": inventory_symbols,
            "governor_date": governor_date,
            "governor_anchor_date": governor_date,
            "daily_anchor_status": "ACTIVE",
            "reason": monitoring_reason,
            "next_action": "MONITOR",
            "next_check_seconds": DEFAULT_POLL_SECONDS,
            "previous_strategy": state.get("previous_strategy") if isinstance(state.get("previous_strategy"), dict) else {},
        })

    status = "PENDING_RESET" if has_open_inventory else "EXITING"
    reason = allow_reason or "monitoring"
    if has_open_inventory:
        reason = str(
            refreshed_governor.get("allow_new_orders_reason")
            or f"daily_rollover_exit_pending ({inventory_count} open)"
        )
    elif pre_close_window:
        reason = "pre_close_exit_all"
    elif governor_pending or day_changed:
        reason = allow_reason or "daily_reset_pending"

    return _write_state({
        "status": status,
        "minutes_to_midnight": minutes_to_midnight,
        "pre_close_minutes": DEFAULT_PRE_CLOSE_MINUTES,
        "previous_global_mode": str(state.get("previous_global_mode") or current_mode or ""),
        "current_global_mode": current_mode,
        "forced_exit_all": bool(rollover_active or governor_pending or day_changed),
        "inventory_open_count": inventory_count,
        "inventory_open_symbols": inventory_symbols,
        "governor_date": governor_date,
        "governor_anchor_date": governor_date,
        "daily_anchor_status": str(refreshed_governor.get("daily_reset_pending") and "PENDING" or "ACTIVE"),
        "reason": reason,
        "next_action": "WAIT_FOR_FLATTEN" if has_open_inventory else ("EXIT_ALL" if pre_close_window else "MONITOR"),
        "next_check_seconds": DEFAULT_POLL_SECONDS,
        "previous_strategy": state.get("previous_strategy") if isinstance(state.get("previous_strategy"), dict) else {},
    })


async def run_forever() -> None:
    while True:
        try:
            await evaluate_daily_reset()
        except Exception as exc:
            logger.exception("Daily reset coordinator cycle failed: %s", exc)
            _write_state({
                "status": "BLOCKED_WITH_REASON",
                "reason": str(exc),
                "next_action": "MONITOR",
                "next_check_seconds": DEFAULT_POLL_SECONDS,
            })
        await asyncio.sleep(DEFAULT_POLL_SECONDS)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
