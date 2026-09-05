#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / "state"

sys.path.insert(0, str(ROOT))

try:
    from Core.Support.ki_config import WIB
except ImportError:
    from datetime import timezone, timedelta

    WIB = timezone(timedelta(hours=7))


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"FAIL:{path.name}_invalid_json:{exc}") from exc
    return data if isinstance(data, dict) else {}


def _money(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _close(a: float, b: float, tolerance: float = 1.0) -> bool:
    return abs(a - b) <= tolerance


def main() -> None:
    today = str(datetime.now(WIB).date())
    anchor_path = STATE / "daily_equity_anchor.json"
    lock_path = STATE / "daily_equity_anchor_lock.json"
    governor_path = STATE / "capital_governor.json"
    truth_path = STATE / "live_truth.json"
    dispatcher_path = STATE / "live_order_dispatcher.json"
    kill_switch_path = STATE / "KILL_SWITCH"

    anchor = _load_json(anchor_path)
    lock = _load_json(lock_path)
    governor = _load_json(governor_path)
    truth = _load_json(truth_path)
    dispatcher = _load_json(dispatcher_path)

    if not anchor:
        raise SystemExit("FAIL:daily_equity_anchor_missing")
    if anchor.get("date") != today:
        raise SystemExit(f"FAIL:daily_equity_anchor_stale:{anchor.get('date')}!= {today}")

    max_loss_pct = _money(anchor.get("max_daily_loss_pct"))
    if max_loss_pct != 1.5:
        raise SystemExit(f"FAIL:daily_equity_anchor_bad_loss_pct:{max_loss_pct}")

    warnings: list[str] = []
    if lock:
        lock_date = str(lock.get("date") or "")
        if lock_date and lock_date != today:
            warnings.append(f"stale_anchor_lock_ignored:{lock_date}")
        elif lock_date == today:
            lock_loss_pct = _money(lock.get("max_daily_loss_pct"))
            if lock_loss_pct != 1.5:
                raise SystemExit(f"FAIL:daily_equity_anchor_lock_bad_loss_pct:{lock_loss_pct}")

    if governor:
        if governor.get("date") != today:
            raise SystemExit(f"FAIL:capital_governor_stale:{governor.get('date')}!= {today}")
        if not _close(
            _money(governor.get("start_total_equity_idr")),
            _money(anchor.get("start_equity_idr")),
        ):
            raise SystemExit(
                "FAIL:governor_anchor_start_equity_mismatch:"
                f"{governor.get('start_total_equity_idr')}!={anchor.get('start_equity_idr')}"
            )
        if not _close(
            _money(governor.get("max_daily_loss_idr")),
            _money(anchor.get("max_daily_loss_idr")),
        ):
            raise SystemExit(
                "FAIL:governor_anchor_loss_cap_mismatch:"
                f"{governor.get('max_daily_loss_idr')}!={anchor.get('max_daily_loss_idr')}"
            )

    if truth:
        if truth.get("runtime_mode") != "LIVE_ONLY":
            raise SystemExit(f"FAIL:live_truth_runtime_mode:{truth.get('runtime_mode')}")
        if truth.get("risk_state") not in {"OK", "CAUTION", "LOCKED", "EMERGENCY"}:
            raise SystemExit(f"FAIL:live_truth_bad_risk_state:{truth.get('risk_state')}")

    env_live = None
    env_path = ROOT / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("KIBOT_LIVE_TRADING_ENABLED="):
                env_live = line.split("=", 1)[1].strip().lower()
                break

    dispatcher_live = dispatcher.get("live_trading_enabled") if dispatcher else None
    if kill_switch_path.exists():
        warnings.append("kill_switch_present")
        if env_live == "true":
            raise SystemExit("FAIL:kill_switch_present_but_env_live_true")
        if dispatcher_live is True:
            warnings.append("dispatcher_stale_live_true_while_kill_switch_present")

    print(
        "OK:ANCHOR_CONTRACT "
        f"date={today} risk={truth.get('risk_state', 'UNKNOWN')} "
        f"env_live={env_live if env_live is not None else 'unknown'} "
        f"dispatcher_live={dispatcher_live if dispatcher_live is not None else 'unknown'} "
        f"warnings={warnings}"
    )


if __name__ == "__main__":
    main()
