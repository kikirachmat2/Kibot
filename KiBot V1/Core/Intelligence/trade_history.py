"""Trade history journal for buy/sell lifecycle and realized PnL.

This module complements :mod:`decision_journal` by keeping a compact,
human-readable daily trade trail. It is intentionally lightweight: JSONL per
WIB day, plus a mirrored `TRADE_EVENT` entry in the decision journal so the
existing audit trail stays unified.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = ROOT / "state"
HISTORY_DIR = STATE_DIR / "trade_history"
WIB = timezone(timedelta(hours=int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7"))))


def _now_wib() -> datetime:
    return datetime.now(WIB)


def _json_default(value: Any) -> str:
    return str(value)


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=True, default=_json_default) + "\n")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "None", "nan"):
            return default
        return float(value)
    except Exception:
        return default


def _rp(value: Any) -> str:
    try:
        return f"Rp {float(value):,.0f}".replace(",", ".")
    except Exception:
        return "Rp 0"


def _event_day_file(day: Optional[str] = None) -> Path:
    day = day or _now_wib().date().isoformat()
    return HISTORY_DIR / f"{day}.jsonl"


def _mirror_to_decision_journal(record: Dict[str, Any]) -> None:
    try:
        from Core.Intelligence.decision_journal import log_event

        payload = dict(record)
        trade_event_type = str(payload.get("event_type") or "").upper()
        payload.pop("event_type", None)
        payload["trade_event_type"] = trade_event_type
        payload["journal_source"] = "trade_history"
        log_event("TRADE_EVENT", payload)
    except Exception:
        pass


def record_trade_event(event_type: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Append a normalized trade lifecycle event and mirror it to the main journal."""
    now = _now_wib()
    payload = payload if isinstance(payload, dict) else {}
    record = {
        "event_type": str(event_type or "TRADE_EVENT").upper(),
        "trade_event_type": str(event_type or "TRADE_EVENT").upper(),
        "ts": time.time(),
        "timestamp_wib": now.isoformat(),
        "date_wib": now.date().isoformat(),
        "source": str(payload.get("source") or "unknown"),
        "venue": str(payload.get("venue") or payload.get("exchange") or "unknown").lower(),
        "symbol": str(payload.get("symbol") or payload.get("pair") or "").upper(),
        "pair": str(payload.get("pair") or payload.get("symbol") or "").upper(),
        "side": str(payload.get("side") or "").upper(),
        "status": str(payload.get("status") or payload.get("state") or "").upper(),
        "reason": str(payload.get("reason") or ""),
        "order_id": str(payload.get("order_id") or ""),
        "sovereign_order_id": str(payload.get("sovereign_order_id") or ""),
        "exchange_order_id": str(payload.get("exchange_order_id") or ""),
        "trade_profile": str(payload.get("trade_profile") or ""),
        "lifecycle": str(payload.get("lifecycle") or ""),
        "state": str(payload.get("state") or ""),
        "price_idr": _safe_float(payload.get("price_idr") or payload.get("fill_price") or payload.get("price"), 0.0),
        "amount_coin": _safe_float(payload.get("amount_coin") or payload.get("coin_amount") or payload.get("amount"), 0.0),
        "amount_idr": _safe_float(payload.get("amount_idr") or payload.get("notional_idr") or payload.get("filled_rp") or payload.get("budget_idr"), 0.0),
        "entry_price_idr": _safe_float(payload.get("entry_price_idr") or payload.get("entry_price"), 0.0),
        "exit_price_idr": _safe_float(payload.get("exit_price_idr") or payload.get("exit_price"), 0.0),
        "fee_idr": _safe_float(payload.get("fee_idr") or payload.get("fee"), 0.0),
        "gross_realized_pnl_idr": _safe_float(payload.get("gross_realized_pnl_idr"), 0.0),
        "net_realized_pnl_idr": _safe_float(payload.get("net_realized_pnl_idr"), 0.0),
        "realized_pnl_idr": _safe_float(payload.get("realized_pnl_idr") or payload.get("pnl_idr"), 0.0),
        "realized_pnl_pct": _safe_float(payload.get("realized_pnl_pct") or payload.get("pnl_pct"), 0.0),
        "note": str(payload.get("note") or payload.get("message") or ""),
        "extras": payload.get("extras") if isinstance(payload.get("extras"), dict) else {},
    }
    _append_jsonl(_event_day_file(), record)
    _mirror_to_decision_journal(record)
    return record


def read_today_events(limit: int = 500) -> List[Dict[str, Any]]:
    path = _event_day_file()
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as fp:
            for line in fp:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return rows[-limit:]


def _activity_from_event(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(row, dict):
        return None
    kind = str(row.get("trade_event_type") or row.get("event_type") or "").upper()
    pair = str(row.get("pair") or row.get("symbol") or "").upper()
    ts = str(row.get("timestamp_wib") or "")
    agent = "Trade"

    if kind in {"POSITION_OPENED", "BUY_FILLED", "ORDER_FILLED"}:
        price = _safe_float(row.get("price_idr"), 0.0)
        amount = _safe_float(row.get("amount_coin"), 0.0)
        amount_idr = _safe_float(row.get("amount_idr"), 0.0)
        if price <= 0 and amount_idr > 0 and amount > 0:
            price = amount_idr / max(amount, 1e-9)
        msg = f"{pair} @ {_rp(price)} x {amount:.6f}".rstrip("0").rstrip(".")
        return {"time": ts, "agent": agent, "tag": "BUY", "message": msg, "offset": "0"}

    if kind in {"POSITION_CLOSED", "SELL_FILLED", "ORDER_RECONCILED"}:
        pnl = _safe_float(row.get("net_realized_pnl_idr") or row.get("realized_pnl_idr"), 0.0)
        pct = _safe_float(row.get("realized_pnl_pct"), 0.0)
        fee = _safe_float(row.get("fee_idr"), 0.0)
        label = "SELL PROFIT" if pnl >= 0 else "SELL LOSS"
        msg = f"{pair} net {_rp(abs(pnl))} ({pct:+.2f}%)"
        if fee > 0:
            msg += f" fee {_rp(fee)}"
        return {"time": ts, "agent": agent, "tag": label, "message": msg, "offset": "0"}

    if kind in {"ENTRY_PENDING", "ORDER_CREATED", "ORDER_SUBMITTED", "ORDER_ACCEPTED", "ENTRY_PARTIAL"}:
        budget = _safe_float(row.get("amount_idr"), 0.0)
        price = _safe_float(row.get("price_idr") or row.get("fill_price"), 0.0)
        amount = _safe_float(row.get("amount_coin"), 0.0)
        if amount <= 0 and price > 0 and budget > 0:
            amount = budget / max(price, 1e-9)
        msg = f"{pair} pending buy {_rp(budget)} @ {_rp(price)}"
        if amount > 0:
            msg += f" x {amount:.6f}".rstrip("0").rstrip(".")
        return {"time": ts, "agent": agent, "tag": "BUY PENDING", "message": msg, "offset": "0"}

    if kind in {"EXIT_PENDING", "ORDER_CANCEL_REQUESTED", "ORDER_PARTIAL_EXIT"}:
        amount = _safe_float(row.get("amount_coin"), 0.0)
        price = _safe_float(row.get("price_idr") or row.get("fill_price"), 0.0)
        msg = f"{pair} pending sell {_rp(price)}"
        if amount > 0:
            msg += f" x {amount:.6f}".rstrip("0").rstrip(".")
        return {"time": ts, "agent": agent, "tag": "SELL PENDING", "message": msg, "offset": "0"}

    if kind in {"ENTRY_REJECTED", "ORDER_FAILED"}:
        reason = str(row.get("reason") or "rejected").strip()
        msg = f"{pair} buy rejected: {reason}"
        return {"time": ts, "agent": agent, "tag": "BUY REJECTED", "message": msg, "offset": "0"}

    if kind in {"EXIT_REJECTED"}:
        reason = str(row.get("reason") or "rejected").strip()
        msg = f"{pair} sell rejected: {reason}"
        return {"time": ts, "agent": agent, "tag": "SELL REJECTED", "message": msg, "offset": "0"}

    if kind in {"ORDER_STALE"}:
        reason = str(row.get("reason") or "stale").strip()
        msg = f"{pair} stale: {reason}"
        return {"time": ts, "agent": agent, "tag": "STALE", "message": msg, "offset": "0"}

    return None


def summarize_today(limit: int = 2000) -> Dict[str, Any]:
    rows = read_today_events(limit=limit)
    summary = {
        "event_count": len(rows),
        "buy_fills": 0,
        "sell_fills": 0,
        "wins": 0,
        "losses": 0,
        "pending_entries": 0,
        "pending_exits": 0,
        "rejections": 0,
        "stale": 0,
        "realized_pnl_idr": 0.0,
        "fee_paid_idr": 0.0,
        "best_win_idr": None,
        "worst_loss_idr": None,
        "recent_activity": [],
        "latest_event": None,
    }
    recent_activity: List[Dict[str, Any]] = []
    seen_buy_keys = set()
    seen_sell_keys = set()

    for row in rows:
        kind = str(row.get("trade_event_type") or row.get("event_type") or "").upper()
        primary_id = str(
            row.get("sovereign_order_id")
            or row.get("order_id")
            or row.get("exchange_order_id")
            or row.get("pair")
            or row.get("symbol")
            or ""
        )
        buy_related = kind in {"POSITION_OPENED", "BUY_FILLED", "ORDER_FILLED"}
        sell_related = kind in {"POSITION_CLOSED", "SELL_FILLED", "ORDER_RECONCILED"}
        activity = _activity_from_event(row)

        if buy_related:
            if primary_id and primary_id in seen_buy_keys:
                summary["latest_event"] = row
                continue
            if primary_id:
                seen_buy_keys.add(primary_id)
            summary["buy_fills"] += 1
            if activity:
                recent_activity.append(activity)
            summary["latest_event"] = row
            continue

        if sell_related:
            if primary_id and primary_id in seen_sell_keys:
                summary["latest_event"] = row
                continue
            if primary_id:
                seen_sell_keys.add(primary_id)
            summary["sell_fills"] += 1
            pnl = _safe_float(row.get("net_realized_pnl_idr") or row.get("realized_pnl_idr"), 0.0)
            summary["fee_paid_idr"] += _safe_float(row.get("fee_idr"), 0.0)
            summary["realized_pnl_idr"] += pnl
            if pnl >= 0:
                summary["wins"] += 1
                if summary["best_win_idr"] is None or pnl > float(summary["best_win_idr"]):
                    summary["best_win_idr"] = pnl
            else:
                summary["losses"] += 1
                if summary["worst_loss_idr"] is None or pnl < float(summary["worst_loss_idr"]):
                    summary["worst_loss_idr"] = pnl
            if activity:
                recent_activity.append(activity)
            summary["latest_event"] = row
            continue

        elif kind in {"ENTRY_PENDING"}:
            summary["pending_entries"] += 1
        elif kind in {"EXIT_PENDING"}:
            summary["pending_exits"] += 1
        elif kind in {"ENTRY_REJECTED", "EXIT_REJECTED", "ORDER_FAILED"}:
            summary["rejections"] += 1
        elif kind in {"ORDER_STALE"}:
            summary["stale"] += 1

        summary["latest_event"] = row
        if activity:
            recent_activity.append(activity)

    recent_activity = list(reversed(recent_activity[-20:]))
    summary["recent_activity"] = recent_activity
    if summary["best_win_idr"] is not None:
        summary["best_win_idr"] = round(float(summary["best_win_idr"]), 2)
    if summary["worst_loss_idr"] is not None:
        summary["worst_loss_idr"] = round(float(summary["worst_loss_idr"]), 2)
    summary["realized_pnl_idr"] = round(float(summary["realized_pnl_idr"]), 2)
    summary["fee_paid_idr"] = round(float(summary["fee_paid_idr"]), 2)
    return summary
