from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from Core.Support.ki_config import STATE_DIR

STATE = Path(STATE_DIR)
WIB = ZoneInfo("Asia/Jakarta")
OUT_FILE = STATE / "pnl_reconciliation.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "None", "nan"):
            return default
        return float(value)
    except Exception:
        return default


def _today_wib() -> str:
    return datetime.now(WIB).date().isoformat()


def _trade_is_from_today(trade: Dict[str, Any]) -> bool:
    ts = _safe_float(trade.get("time") or trade.get("ts") or trade.get("created_at_ts"), 0.0)
    if ts <= 0.0:
        return False
    try:
        return datetime.fromtimestamp(ts, tz=WIB).date().isoformat() == _today_wib()
    except Exception:
        return False


def _legacy_modes(venue_ledger: Dict[str, Any]) -> List[str]:
    legacy_terms = ("paper", "simulation", "shadow", "mock", "canary", "view-only")
    hits = []
    for key, value in (venue_ledger or {}).items():
        blob = f"{key} {json.dumps(value, default=str)}".lower()
        if any(term in blob for term in legacy_terms):
            hits.append(str(key))
    return hits


def reconcile_pnl_state(write: bool = True) -> Dict[str, Any]:
    gov = _read_json(STATE / "capital_governor.json", {})
    anchor = _read_json(STATE / "daily_equity_anchor.json", {})
    venue_ledger = _read_json(STATE / "venue_ledger.json", {})
    active_trades = _read_json(STATE / "active_trades.json", {})

    gov_start = _safe_float(gov.get("start_total_equity_idr"), 0.0)
    gov_current = _safe_float(gov.get("current_total_equity_idr"), 0.0)
    gov_daily = _safe_float(gov.get("daily_pnl_idr"), 0.0)
    gov_cap = _safe_float(gov.get("max_daily_loss_idr"), 0.0)

    anchor_start = _safe_float(anchor.get("start_equity_idr"), 0.0)
    anchor_cap = _safe_float(anchor.get("max_daily_loss_idr"), 0.0)
    canonical_start = anchor_start or gov_start
    canonical_cap = anchor_cap or gov_cap or canonical_start * 0.015
    canonical_daily = gov_current - canonical_start
    risk_remaining = max(0.0, canonical_cap + canonical_daily)
    hard_stop = bool(canonical_cap > 0.0 and canonical_daily <= -canonical_cap)

    legacy_open_positions = []
    today_open_positions = []
    if isinstance(active_trades, dict):
        for pair, trade in active_trades.items():
            if not isinstance(trade, dict):
                continue
            item = {
                "pair": str(pair),
                "cost_idr": _safe_float(trade.get("cost") or trade.get("budget_idr") or trade.get("notional_idr"), 0.0),
                "amount": _safe_float(trade.get("amount"), 0.0),
                "exit_blocked_reason": str(trade.get("exit_blocked_reason") or ""),
            }
            if _trade_is_from_today(trade):
                today_open_positions.append(item)
            else:
                legacy_open_positions.append(item)

    discrepancies = []
    if anchor_start and gov_start and abs(anchor_start - gov_start) > max(1000.0, anchor_start * 0.01):
        discrepancies.append({
            "type": "ANCHOR_GOVERNOR_MISMATCH",
            "anchor_start_equity_idr": anchor_start,
            "governor_start_equity_idr": gov_start,
            "severity": "HIGH",
        })
    legacy = _legacy_modes(venue_ledger if isinstance(venue_ledger, dict) else {})
    if legacy:
        discrepancies.append({
            "type": "LEGACY_LEDGER_ROWS",
            "rows": legacy,
            "severity": "HIGH",
        })
    if legacy_open_positions:
        discrepancies.append({
            "type": "LEGACY_OPEN_POSITION_DRAG",
            "positions": legacy_open_positions,
            "severity": "MEDIUM",
        })
    if abs(canonical_daily - gov_daily) > max(500.0, abs(canonical_daily) * 0.02):
        discrepancies.append({
            "type": "CANONICAL_GOVERNOR_PNL_MISMATCH",
            "canonical_daily_pnl_idr": canonical_daily,
            "governor_daily_pnl_idr": gov_daily,
            "severity": "HIGH",
        })

    what_if_checks = [
        {
            "name": "what_if_anchor_drifts",
            "status": "FAIL" if any(d.get("type") == "ANCHOR_GOVERNOR_MISMATCH" for d in discrepancies) else "PASS",
            "action": "force_daily_anchor_as_canonical_start",
        },
        {
            "name": "what_if_legacy_position_masks_today",
            "status": "WARN" if legacy_open_positions else "PASS",
            "action": "separate_legacy_open_drag_from_today_trade_pnl",
        },
        {
            "name": "what_if_hard_stop_breached",
            "status": "FAIL" if hard_stop else "PASS",
            "action": "exit_only_no_new_entries",
        },
        {
            "name": "what_if_ledger_contains_non_live_rows",
            "status": "FAIL" if legacy else "PASS",
            "action": "purge_non_live_rows_from_production_ledger",
        },
    ]

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "date": _today_wib(),
        "canonical": {
            "start_equity_idr": canonical_start,
            "current_total_equity_idr": gov_current,
            "daily_pnl_idr": canonical_daily,
            "max_daily_loss_idr": canonical_cap,
            "risk_remaining_idr": risk_remaining,
            "hard_stop": hard_stop,
            "source": "daily_equity_anchor+capital_governor_current",
        },
        "governor": {
            "start_equity_idr": gov_start,
            "current_total_equity_idr": gov_current,
            "daily_pnl_idr": gov_daily,
            "max_daily_loss_idr": gov_cap,
            "allow_new_orders": bool(gov.get("allow_new_orders", False)),
            "status": str(gov.get("status") or ""),
        },
        "anchor": anchor,
        "legacy_open_positions": legacy_open_positions,
        "today_open_positions": today_open_positions,
        "discrepancies": discrepancies,
        "what_if_checks": what_if_checks,
        "final_order_permission": {
            "allow_new_orders": bool(gov.get("allow_new_orders", False)) and not hard_stop and not any(d.get("severity") == "HIGH" and d.get("type") == "ANCHOR_GOVERNOR_MISMATCH" for d in discrepancies),
            "reason": "hard_stop_or_reconciliation_mismatch" if hard_stop or discrepancies else "reconciled",
        },
    }

    if write:
        STATE.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps(reconcile_pnl_state(write=True), indent=2))
