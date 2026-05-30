from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = ROOT / "state"
GOVERNOR_FILE = STATE_DIR / "capital_governor.json"
PHANTOM_FILE = STATE_DIR / "phantom_treasury.json"
LIVE_TRUTH_FILE = STATE_DIR / "live_truth.json"


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
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def build_accounting_truth() -> Dict[str, Any]:
    """Return a single canonical total-saldo snapshot.

    Priority order:
    1. Fresh governor state.
    2. Governor state even if stale, when it still exposes current totals.
    3. Live venue fallback assembled from Indodax + Phantom treasury.

    The dashboard and reporting layers should use this as their one balance
    contract so holdings never appear to disappear while positions are open.
    """

    live_truth = _read_json(LIVE_TRUTH_FILE, {})
    if isinstance(live_truth, dict) and live_truth:
        wallet_equity = _safe_float(live_truth.get("wallet_equity_idr"), 0.0)
        cash_idr = _safe_float(live_truth.get("cash_idr"), 0.0)
        net_pnl = _safe_float(live_truth.get("net_pnl_today_idr"), 0.0)
        reset_total = max(0.0, wallet_equity - net_pnl)
        return {
            "updated_at": live_truth.get("updated_at", datetime.now(timezone.utc).isoformat()),
            "source": "live_truth",
            "live_total_equity_idr": wallet_equity,
            "governor_fresh": True,
            "date": str(live_truth.get("updated_at", "")).split("T", 1)[0],
            "current_total_equity_idr": wallet_equity,
            "total_balance_idr": wallet_equity,
            "reset_total_balance_idr": reset_total,
            "start_total_equity_idr": reset_total,
            "daily_pnl_idr": net_pnl,
            "combined_pnl_idr": net_pnl,
            "daily_return_idr": net_pnl,
            "daily_pnl_pct": 0.0,
            "daily_return_pct": 0.0,
            "indodax_equity_idr": _safe_float(live_truth.get("indodax_equity_idr"), 0.0),
            "phantom_equity_idr": _safe_float(live_truth.get("phantom_equity_idr"), 0.0),
            "in_flight_idr": 0.0,
            "open_buy_order_reserve_idr": 0.0,
            "components": {
                "indodax": _safe_float(live_truth.get("indodax_equity_idr"), 0.0),
                "phantom": _safe_float(live_truth.get("phantom_equity_idr"), 0.0),
                "cash": cash_idr,
            },
            "capital_governor": {},
            "phantom_treasury": live_truth,
        }

    gov = _read_json(GOVERNOR_FILE, {})
    phantom = _read_json(PHANTOM_FILE, {})
    today = datetime.now(timezone.utc).astimezone().date().isoformat()
    gov_date = str(gov.get("date") or "").strip()
    governor_fresh = bool(gov and gov_date == today)

    indodax_equity = _safe_float(
        (gov.get("venues", {}) or {}).get("indodax", {}).get("equity_idr"),
        _safe_float(gov.get("current_indodax_equity_idr"), 0.0),
    )
    phantom_equity = _safe_float(
        (gov.get("venues", {}) or {}).get("phantom", {}).get("equity_idr"),
        _safe_float(
            phantom.get("total_value_idr"),
            _safe_float(phantom.get("chains", {}).get("base", {}).get("value_idr"), 0.0),
        ),
    )
    in_flight_idr = _safe_float(gov.get("in_flight_idr"), 0.0)
    open_buy_order_reserve_idr = _safe_float(gov.get("open_buy_order_reserve_idr"), 0.0)

    live_total_equity_idr = indodax_equity + phantom_equity + in_flight_idr
    current_total_equity_idr = _safe_float(gov.get("current_total_equity_idr"), 0.0)
    if not governor_fresh or current_total_equity_idr <= 0.0:
        current_total_equity_idr = live_total_equity_idr

    reset_total_balance_idr = _safe_float(
        gov.get("reset_total_balance_idr"),
        _safe_float(gov.get("start_total_equity_idr"), current_total_equity_idr),
    )
    daily_pnl_idr = _safe_float(
        gov.get("daily_pnl_idr"),
        _safe_float(gov.get("combined_pnl_idr"), current_total_equity_idr - reset_total_balance_idr),
    )
    daily_pnl_pct = _safe_float(
        gov.get("daily_pnl_pct"),
        _safe_float(gov.get("daily_return_pct"), (daily_pnl_idr / max(reset_total_balance_idr, 1.0)) * 100.0),
    )

    if not governor_fresh:
        daily_pnl_idr = current_total_equity_idr - reset_total_balance_idr
        daily_pnl_pct = (daily_pnl_idr / max(reset_total_balance_idr, 1.0)) * 100.0

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "capital_governor" if governor_fresh and _safe_float(gov.get("current_total_equity_idr"), 0.0) > 0.0 else "live_venue_fallback",
        "live_total_equity_idr": live_total_equity_idr,
        "governor_fresh": governor_fresh,
        "date": gov_date,
        "current_total_equity_idr": current_total_equity_idr,
        "total_balance_idr": current_total_equity_idr,
        "reset_total_balance_idr": reset_total_balance_idr,
        "start_total_equity_idr": reset_total_balance_idr,
        "daily_pnl_idr": daily_pnl_idr,
        "combined_pnl_idr": daily_pnl_idr,
        "daily_return_idr": daily_pnl_idr,
        "daily_pnl_pct": daily_pnl_pct,
        "daily_return_pct": daily_pnl_pct,
        "indodax_equity_idr": indodax_equity,
        "phantom_equity_idr": phantom_equity,
        "in_flight_idr": in_flight_idr,
        "open_buy_order_reserve_idr": open_buy_order_reserve_idr,
        "components": {
            "indodax": indodax_equity,
            "phantom": phantom_equity,
            "in_flight": in_flight_idr,
            "open_buy_order_reserve": open_buy_order_reserve_idr,
        },
        "capital_governor": gov,
        "phantom_treasury": phantom,
    }
