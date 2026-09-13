from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from Core.Support.ki_config import STATE_DIR


ROUND_TRIP_DIR = STATE_DIR / "round_trips"
OPEN_FILE = ROUND_TRIP_DIR / "open_round_trips.json"
CLOSED_FILE = ROUND_TRIP_DIR / "closed_round_trips.jsonl"
ERROR_FILE = ROUND_TRIP_DIR / "accounting_errors.jsonl"


def _ensure_dir() -> None:
    ROUND_TRIP_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, (dict, list)) else default
    except Exception:
        return default
    return default


def _read_jsonl(path: Path) -> List[dict]:
    rows: List[dict] = []
    if not path.exists():
        return rows
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except Exception:
                continue
    except Exception:
        return rows
    return rows


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    _ensure_dir()
    with open(path, "a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "None", "nan"):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _normalize_symbol(value: Any) -> str:
    raw = str(value or "").strip().upper().replace("-", "_").replace("/", "_")
    if raw.endswith("IDR") and not raw.endswith("_IDR"):
        raw = raw[:-3] + "_IDR"
    return raw


def _event_rows(bundle: Dict[str, Any] | None = None) -> List[dict]:
    bundle = bundle or {}
    rows: List[dict] = []
    if isinstance(bundle.get("trade_history"), list) and bundle.get("trade_history"):
        rows = [row for row in bundle.get("trade_history", []) if isinstance(row, dict)]
    else:
        trade_dir = STATE_DIR / "trade_history"
        if trade_dir.exists():
            for file in sorted(trade_dir.glob("*.jsonl")):
                rows.extend(_read_jsonl(file))
    return rows


def _event_is_fill(row: dict) -> bool:
    et = str(row.get("event_type") or row.get("trade_event_type") or "").upper()
    st = str(row.get("status") or "").upper()
    side = str(row.get("side") or "").upper()
    return et in {"ORDER_FILLED", "ORDER_RECONCILED", "POSITION_OPENED", "POSITION_CLOSED"} or st in {"FILLED", "CLOSED", "RECONCILED"} or side in {"BUY", "SELL"}


def _event_key(row: dict) -> Tuple[str, str, str]:
    venue = str(row.get("venue") or row.get("source") or "unknown").lower()
    symbol = _normalize_symbol(row.get("pair") or row.get("symbol"))
    side = str(row.get("side") or "").upper()
    return venue, symbol, side


def _dedupe_rows(rows: Iterable[dict]) -> List[dict]:
    seen = set()
    out = []
    for row in rows:
        key = (
            str(row.get("exchange_order_id") or row.get("order_id") or row.get("sovereign_order_id") or ""),
            str(row.get("event_type") or row.get("trade_event_type") or ""),
            str(row.get("ts") or row.get("timestamp_wib") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def build_round_trip_accounting(bundle: Dict[str, Any] | None = None) -> Dict[str, Any]:
    _ensure_dir()
    rows = _dedupe_rows([row for row in _event_rows(bundle) if _event_is_fill(row)])
    grouped: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for row in rows:
        venue, symbol, _side = _event_key(row)
        if not symbol:
            continue
        grouped[(venue, symbol)].append(row)

    open_round_trips: List[dict] = []
    closed_rows: List[dict] = []
    error_rows: List[dict] = []

    for (venue, symbol), items in grouped.items():
        items = sorted(items, key=lambda r: _parse_dt(r.get("timestamp_wib")) or _parse_dt(r.get("updated_at")) or datetime.now(timezone.utc))
        buys = [r for r in items if str(r.get("side") or "").upper() == "BUY"]
        sells = [r for r in items if str(r.get("side") or "").upper() == "SELL"]
        if not buys and not sells:
            continue

        strategy = str((items[0].get("trade_profile") or items[0].get("lifecycle") or items[0].get("source") or "unknown"))
        tier = str(items[0].get("tier") or items[0].get("trade_grade") or items[0].get("label") or "UNKNOWN")
        entry_notional = sum(_safe_float(r.get("amount_idr") or r.get("budget_idr"), 0.0) for r in buys)
        exit_notional = sum(_safe_float(r.get("amount_idr") or r.get("notional_idr"), 0.0) for r in sells)
        fees = sum(_safe_float(r.get("fee_idr"), 0.0) for r in items)
        gross = sum(_safe_float(r.get("gross_realized_pnl_idr"), 0.0) for r in sells) or (exit_notional - entry_notional)
        net = sum(_safe_float(r.get("net_realized_pnl_idr"), _safe_float(r.get("realized_pnl_idr"), 0.0)) for r in sells)
        if net == 0.0 and gross != 0.0 and fees:
            net = gross - fees
        opened_at = min((_parse_dt(r.get("timestamp_wib")) or _parse_dt(r.get("updated_at")) or datetime.now(timezone.utc) for r in items))
        closed_at = max((_parse_dt(r.get("timestamp_wib")) or _parse_dt(r.get("updated_at")) or datetime.now(timezone.utc) for r in items))
        hold_seconds = int((closed_at - opened_at).total_seconds()) if closed_at and opened_at else 0
        status = "CLOSED" if buys and sells else "OPEN"
        exit_reason = str((sells[-1].get("reason") or sells[-1].get("note") or "") if sells else "")
        warnings = []
        if not buys or not sells:
            status = "OPEN"
            warnings.append("missing_entry_or_exit")
        if any("PARTIAL" in str(r.get("status") or "").upper() for r in items):
            status = "PARTIAL"
            warnings.append("partial_fill_present")
        if entry_notional <= 0 or exit_notional <= 0:
            warnings.append("zero_notional")
        rt = {
            "round_trip_id": f"{venue}:{symbol}:{int(opened_at.timestamp()) if opened_at else 0}",
            "venue": venue,
            "symbol": symbol,
            "strategy": strategy,
            "tier": tier,
            "entry_order_ids": [str(r.get("order_id") or r.get("exchange_order_id") or "") for r in buys if r.get("order_id") or r.get("exchange_order_id")],
            "exit_order_ids": [str(r.get("order_id") or r.get("exchange_order_id") or "") for r in sells if r.get("order_id") or r.get("exchange_order_id")],
            "entry_fills": buys,
            "exit_fills": sells,
            "entry_notional_idr": round(entry_notional, 2),
            "exit_notional_idr": round(exit_notional, 2),
            "gross_pnl_idr": round(gross, 2),
            "fees_idr": round(fees, 2),
            "spread_cost_est_idr": 0.0,
            "slippage_est_idr": 0.0,
            "net_pnl_idr": round(net, 2),
            "hold_seconds": hold_seconds,
            "status": status if status in {"OPEN", "CLOSED", "DUST_BLOCKED", "PARTIAL", "ACCOUNTING_ERROR"} else "ACCOUNTING_ERROR",
            "opened_at": opened_at.astimezone(timezone.utc).isoformat() if opened_at else "",
            "closed_at": closed_at.astimezone(timezone.utc).isoformat() if closed_at else None,
            "exit_reason": exit_reason,
            "accounting_warnings": warnings,
        }
        if status == "CLOSED":
            closed_rows.append(rt)
        elif status == "OPEN":
            open_round_trips.append(rt)
        else:
            error_rows.append(rt)

    OPEN_FILE.write_text(json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "open_round_trips": open_round_trips}, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(CLOSED_FILE, "a", encoding="utf-8") as fp:
        for row in closed_rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(ERROR_FILE, "a", encoding="utf-8") as fp:
        for row in error_rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "round_trips": closed_rows + open_round_trips + error_rows,
        "open_round_trips": open_round_trips,
        "closed_round_trips": closed_rows,
        "accounting_errors": error_rows,
        "stats": {
            "closed_round_trips": len(closed_rows),
            "open_round_trips": len(open_round_trips),
            "accounting_errors": len(error_rows),
            "gross_pnl_idr": round(sum(r.get("gross_pnl_idr", 0.0) for r in closed_rows), 2),
            "fees_idr": round(sum(r.get("fees_idr", 0.0) for r in closed_rows), 2),
            "net_pnl_idr": round(sum(r.get("net_pnl_idr", 0.0) for r in closed_rows), 2),
        },
    }
    (STATE_DIR / "round_trip_accounting.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary

