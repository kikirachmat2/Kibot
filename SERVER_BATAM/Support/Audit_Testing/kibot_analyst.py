#!/usr/bin/env python3
"""
KiBot Data Analyst
==================
Independent bulkhead for trade/system journaling and daily summaries.
This process never makes trading decisions.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(os.getenv("KIBOT_RUNTIME_ROOT", Path(__file__).resolve().parent.parent))
STATE_DIR = ROOT / "state"
ANALYST_DIR = STATE_DIR / "analyst"
EVENTS_DIR = STATE_DIR / "events"
TRADE_LOG = STATE_DIR / "trade_log.jsonl"
LEGACY_ANALYST_TRADE_LOG = ANALYST_DIR / "trade_log.jsonl"
BALANCE_LOG = ANALYST_DIR / "balance_snapshots.jsonl"
FAILURE_LOG = ANALYST_DIR / "failures.jsonl"
BEHAVIOR_LOG = ANALYST_DIR / "behavior.jsonl"
DAILY_SUMMARY = ANALYST_DIR / "daily_summary.json"
SUMMARY_HISTORY = ANALYST_DIR / "analyst_daily.json"
WIB_UTC_OFFSET_HOURS = int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7"))
ANALYST_INTERVAL_SECONDS = int(os.getenv("KIBOT_ANALYST_INTERVAL_SECONDS", "600"))

DEMO_TRADE_SIGNATURES = {
    ("BUY", 400.0, 401.0, 40100.0, 60.15, "", "BUCKET_B", 0.88),
    ("SELL", 450.0, 449.0, 44900.0, 67.35, "PARTIAL_TP_1", "BUCKET_A", 0.0),
}
DEMO_FAILURE_SIGNATURE = (
    "kibot-executor-indodax",
    "INSUFFICIENT_BALANCE",
    "Cannot buy bio_idr: free IDR 1051 < required 8000",
)


def ensure_dirs() -> None:
    ANALYST_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def today_wib_str() -> str:
    return (now_utc() + timedelta(hours=WIB_UTC_OFFSET_HOURS)).strftime("%Y-%m-%d")


def atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _push_event(event_type: str, data: Dict[str, Any]) -> None:
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    event_file = EVENTS_DIR / f"{event_type}_{int(time.time() * 1000)}.json"
    payload = {"type": event_type, "ts": now_iso(), "data": data}
    atomic_write(event_file, payload)


def record_trade(
    pair: str,
    side: str,
    order_type: str,
    requested_price: float,
    filled_price: float,
    filled_idr: float,
    fee_idr: float,
    net_pnl_pct: float = 0.0,
    net_pnl_idr: float = 0.0,
    holding_ms: int = 0,
    exit_reason: str = "",
    signal_source: str = "UNKNOWN",
    bucket: str = "BUCKET_A",
    conviction_score: float = 0.0,
    success: bool = True,
    error_msg: str = "",
) -> None:
    record = {
        "ts": now_iso(),
        "event": "TRADE_BUY" if side.upper() == "BUY" else "TRADE_SELL",
        "pair": pair,
        "side": side.upper(),
        "order_type": order_type.upper(),
        "requested_price": requested_price,
        "filled_price": filled_price,
        "filled_idr": filled_idr,
        "fee_idr": fee_idr,
        "net_pnl_pct": net_pnl_pct,
        "net_pnl_idr": net_pnl_idr,
        "holding_ms": holding_ms,
        "exit_reason": exit_reason,
        "signal_source": signal_source,
        "bucket": bucket,
        "conviction_score": conviction_score,
        "success": success,
        "error_msg": error_msg,
    }
    append_jsonl(TRADE_LOG, record)
    _update_daily_summary()


def record_failure(
    service: str,
    error_type: str,
    message: str,
    severity: str = "ERROR",
    context: Optional[Dict[str, Any]] = None,
) -> None:
    record = {
        "ts": now_iso(),
        "service": service,
        "error_type": error_type,
        "message": message,
        "severity": severity,
        "context": context or {},
    }
    append_jsonl(FAILURE_LOG, record)
    if severity.upper() == "CRITICAL":
        _push_event("CRITICAL_FAILURE", record)


def record_behavior(action: str, pair: str = "", reason: str = "", details: Optional[Dict[str, Any]] = None) -> None:
    record = {"ts": now_iso(), "action": action, "pair": pair, "reason": reason, "details": details or {}}
    append_jsonl(BEHAVIOR_LOG, record)


def record_balance(total_idr: float, free_idr: float, in_positions_idr: float, daily_pnl_pct: float, active_positions: int) -> None:
    record = {
        "ts": now_iso(),
        "total_idr": total_idr,
        "free_idr": free_idr,
        "in_positions_idr": in_positions_idr,
        "daily_pnl_pct": daily_pnl_pct,
        "active_positions": active_positions,
    }
    append_jsonl(BALANCE_LOG, record)
    if daily_pnl_pct <= -0.02:
        _push_event("DAILY_DRAWDOWN_ALERT", record)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _read_trade_log_records() -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for path in (TRADE_LOG, LEGACY_ANALYST_TRADE_LOG):
        for record in _read_jsonl(path):
            signature = json.dumps(
                {
                    "ts": record.get("timestamp") or record.get("ts"),
                    "pair": record.get("pair"),
                    "side": record.get("side"),
                    "filled_price": record.get("filledPrice") or record.get("filled_price"),
                    "filled_idr": record.get("filledIdr") or record.get("filled_idr"),
                    "net_pnl_pct": record.get("netPnlPct") or record.get("net_pnl_pct"),
                },
                sort_keys=True,
                ensure_ascii=False,
            )
            if signature in seen:
                continue
            seen.add(signature)
            records.append(record)
    return records


def _extract_reason_pnl_pct(exit_reason: Any) -> float | None:
    text = str(exit_reason or "").strip()
    if not text:
        return None
    match = re.search(r"\bpnl=([+-]?\d+(?:\.\d+)?)%", text, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"\bat ([+-]?\d+(?:\.\d+)?)%", text, flags=re.IGNORECASE)
        if not match:
            return None
        try:
            value = float(match.group(1))
        except Exception:
            return None
        if value < 0.0:
            return value / 100.0
        return None
    try:
        return float(match.group(1)) / 100.0
    except Exception:
        return None


def _normalized_trade_net_pnl_pct(record: Dict[str, Any]) -> float | None:
    direct = record.get("netPnlPct")
    if direct is None:
        direct = record.get("net_pnl_pct")
    try:
        direct_val = float(direct) if direct is not None else None
    except Exception:
        direct_val = None
    filled_price = record.get("filledPrice")
    if filled_price is None:
        filled_price = record.get("filled_price")
    try:
        filled_price_val = float(filled_price) if filled_price is not None else None
    except Exception:
        filled_price_val = None
    inferred = _extract_reason_pnl_pct(record.get("exitReason") or record.get("exit_reason"))
    if inferred is not None:
        if direct_val is None:
            return inferred
        if filled_price_val is None or filled_price_val <= 0.0 or (direct_val < -0.90 and inferred > 0.0):
            return inferred
    return direct_val


def _normalized_trade_net_pnl_idr(record: Dict[str, Any]) -> float | None:
    direct = record.get("netPnlIdr")
    if direct is None:
        direct = record.get("net_pnl_idr")
    try:
        direct_val = float(direct) if direct is not None else None
    except Exception:
        direct_val = None

    pnl_pct = _normalized_trade_net_pnl_pct(record)
    if pnl_pct is None:
        return direct_val

    requested_price = record.get("requestedPrice")
    if requested_price is None:
        requested_price = record.get("requested_price")
    filled_price = record.get("filledPrice")
    if filled_price is None:
        filled_price = record.get("filled_price")
    filled_amount = record.get("filledAmount")
    if filled_amount is None:
        filled_amount = record.get("filled_amount")
    filled_idr = record.get("filledIdr")
    if filled_idr is None:
        filled_idr = record.get("filled_idr")
    try:
        requested_price_val = float(requested_price) if requested_price is not None else 0.0
    except Exception:
        requested_price_val = 0.0
    try:
        filled_price_val = float(filled_price) if filled_price is not None else 0.0
    except Exception:
        filled_price_val = 0.0
    try:
        filled_amount_val = float(filled_amount) if filled_amount is not None else 0.0
    except Exception:
        filled_amount_val = 0.0
    try:
        filled_idr_val = float(filled_idr) if filled_idr is not None else 0.0
    except Exception:
        filled_idr_val = 0.0

    effective_notional = filled_idr_val
    if effective_notional <= 0.0 and filled_price_val > 0.0 and filled_amount_val > 0.0:
        effective_notional = filled_price_val * filled_amount_val
    if effective_notional <= 0.0 and requested_price_val > 0.0 and filled_amount_val > 0.0:
        effective_notional = requested_price_val * filled_amount_val
    estimated = None
    if effective_notional > 0.0 and pnl_pct > -0.95:
        estimated = (effective_notional * pnl_pct) / (1.0 + pnl_pct)

    if direct_val is None:
        return estimated
    if estimated is None:
        return direct_val
    if filled_price_val <= 0.0 and ((direct_val < 0.0 < pnl_pct) or abs(direct_val) <= 1e-9 or abs(direct_val) > effective_notional * 1.5):
        return estimated
    return direct_val


def _rewrite_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _is_demo_trade(record: Dict[str, Any]) -> bool:
    if str(record.get("pair", "")).lower() != "bio_idr":
        return False
    signature = (
        str(record.get("side", "")).upper(),
        float(record.get("requested_price", 0.0)),
        float(record.get("filled_price", 0.0)),
        float(record.get("filled_idr", 0.0)),
        float(record.get("fee_idr", 0.0)),
        str(record.get("exit_reason", "")),
        str(record.get("bucket", "BUCKET_A")),
        round(float(record.get("conviction_score", 0.0)), 2),
    )
    return signature in DEMO_TRADE_SIGNATURES


def _is_demo_failure(record: Dict[str, Any]) -> bool:
    signature = (
        str(record.get("service", "")),
        str(record.get("error_type", "")),
        str(record.get("message", "")),
    )
    return signature == DEMO_FAILURE_SIGNATURE


def purge_demo_fixture_records() -> None:
    removed = 0

    for trade_log_path in (TRADE_LOG, LEGACY_ANALYST_TRADE_LOG):
        if trade_log_path.exists():
            trades = _read_jsonl(trade_log_path)
            filtered_trades = [row for row in trades if not _is_demo_trade(row)]
            removed += len(trades) - len(filtered_trades)
            if len(filtered_trades) != len(trades):
                _rewrite_jsonl(trade_log_path, filtered_trades)

    if FAILURE_LOG.exists():
        failures = _read_jsonl(FAILURE_LOG)
        filtered_failures = [row for row in failures if not _is_demo_failure(row)]
        removed += len(failures) - len(filtered_failures)
        if len(filtered_failures) != len(failures):
            _rewrite_jsonl(FAILURE_LOG, filtered_failures)

    if removed:
        print(f"[ANALYST] Purged {removed} legacy demo fixture records")


def _read_today_trades() -> List[Dict[str, Any]]:
    today = today_wib_str()
    rows: List[Dict[str, Any]] = []
    for record in _read_trade_log_records():
        ts = str(record.get("timestamp") or record.get("ts") or "").strip()
        if not ts:
            continue
        try:
            parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            trade_day = (parsed.astimezone(timezone.utc) + timedelta(hours=WIB_UTC_OFFSET_HOURS)).strftime("%Y-%m-%d")
        except Exception:
            trade_day = ts[:10]
        if trade_day == today:
            rows.append(record)
    return rows


def _update_history(summary: Dict[str, Any]) -> None:
    history: List[Dict[str, Any]] = []
    if SUMMARY_HISTORY.exists():
        try:
            history = json.loads(SUMMARY_HISTORY.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = []
    history = [item for item in history if item.get("date") != summary.get("date")]
    history.append(summary)
    history = sorted(history, key=lambda item: item.get("date", ""))[-30:]
    atomic_write(SUMMARY_HISTORY, history)


def _update_daily_summary() -> Dict[str, Any]:
    trades = _read_today_trades()
    sells = [trade for trade in trades if trade.get("side") == "SELL"]
    if not sells:
        summary = {"date": today_wib_str(), "no_trades": True}
    else:
        normalized_sells = []
        for sell in sells:
            pnl = _normalized_trade_net_pnl_pct(sell)
            if pnl is None:
                pnl = 0.0
            normalized_sells.append((sell, pnl))
        wins = [(sell, pnl) for sell, pnl in normalized_sells if pnl > 0.0]
        losses = [(sell, pnl) for sell, pnl in normalized_sells if pnl <= 0.0]
        total_fee = sum(float(trade.get("fee_idr") or trade.get("feeIdr") or 0.0) for trade in trades)
        market_orders = [
            trade
            for trade in trades
            if str(trade.get("order_type") or trade.get("orderType") or "").upper() == "MARKET"
        ]
        summary = {
            "date": today_wib_str(),
            "total_trades": len(sells),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / max(1, len(sells)), 3),
            "total_net_pnl_pct": round(sum(pnl for _, pnl in normalized_sells), 4),
            "total_net_pnl_idr": round(sum((_normalized_trade_net_pnl_idr(sell) or 0.0) for sell in sells), 0),
            "total_fee_idr": round(total_fee, 0),
            "market_order_count": len(market_orders),
            "market_order_rate": round(len(market_orders) / max(1, len(trades)), 3),
            "avg_holding_min": round(
                sum(int(sell.get("holding_ms") or sell.get("holdingDurationMs") or 0) for sell in sells)
                / max(1, len(sells))
                / 60000,
                1,
            ),
            "top_losers": sorted(
                [{"pair": sell.get("pair", "?"), "pnl": pnl, "exit": sell.get("exit_reason") or sell.get("exitReason") or "?"} for sell, pnl in losses],
                key=lambda item: item["pnl"],
            )[:5],
            "top_winners": sorted(
                [{"pair": sell.get("pair", "?"), "pnl": pnl} for sell, pnl in wins],
                key=lambda item: -item["pnl"],
            )[:5],
            "bucket_breakdown": {
                "A": len([trade for trade in trades if trade.get("bucket") == "BUCKET_A"]),
                "B": len([trade for trade in trades if trade.get("bucket") == "BUCKET_B"]),
            },
        }
    atomic_write(DAILY_SUMMARY, summary)
    _update_history(summary)
    return summary


def generate_daily_report() -> str:
    if not DAILY_SUMMARY.exists():
        return "📊 Belum ada data trading hari ini."
    try:
        summary = json.loads(DAILY_SUMMARY.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "⚠️ Error membaca data harian."
    if summary.get("no_trades"):
        return f"📊 *KiBot Daily Report* — {summary.get('date', '?')}\n\nTidak ada trade hari ini."
    pnl_pct = float(summary.get("total_net_pnl_pct", 0.0)) * 100
    pnl_idr = float(summary.get("total_net_pnl_idr", 0.0))
    emoji = "🟢" if pnl_pct >= 0 else "🔴"
    lines = [
        f"📊 *KiBot Daily Report* — {summary.get('date', '?')}",
        "",
        f"{emoji} PnL Hari Ini: `{pnl_pct:+.2f}%` (Rp{pnl_idr:,.0f})",
        f"📈 Trades: {summary.get('total_trades', 0)} | Win: {summary.get('wins', 0)} | Loss: {summary.get('losses', 0)}",
        f"🎯 Win Rate: {float(summary.get('win_rate', 0.0)) * 100:.0f}%",
        f"💸 Total Fee: Rp{float(summary.get('total_fee_idr', 0.0)):,.0f}",
        f"⚡ Market Orders: {summary.get('market_order_count', 0)}",
        f"⏱️ Avg Holding: {float(summary.get('avg_holding_min', 0.0)):.0f} menit",
        "",
        "📉 Top Losers:",
    ]
    for loser in summary.get("top_losers", [])[:3]:
        lines.append(f"  • {loser['pair']}: {float(loser['pnl']) * 100:+.2f}% [{loser.get('exit', '?')}]")
    lines.append("")
    lines.append("📈 Top Winners:")
    for winner in summary.get("top_winners", [])[:3]:
        lines.append(f"  • {winner['pair']}: {float(winner['pnl']) * 100:+.2f}%")
    failures_today = 0
    today = today_wib_str()
    for item in _read_jsonl(FAILURE_LOG):
        ts = str(item.get("ts", "")).strip()
        try:
            parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            item_day = (parsed.astimezone(timezone.utc) + timedelta(hours=WIB_UTC_OFFSET_HOURS)).strftime("%Y-%m-%d")
        except Exception:
            item_day = ts[:10]
        if item_day == today:
            failures_today += 1
    lines.append("")
    lines.append(f"⚠️ System Failures Hari Ini: {failures_today}")
    return "\n".join(lines)


def rotate_logs_if_needed(max_size_mb: float = 5.0) -> None:
    if not TRADE_LOG.exists() or TRADE_LOG.stat().st_size / 1_000_000 < max_size_mb:
        return
    cutoff = now_utc() - timedelta(days=30)
    recent_lines: List[str] = []
    archived_lines: List[str] = []
    with open(TRADE_LOG, "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                ts = datetime.fromisoformat(str(record.get("ts")).replace("Z", "+00:00"))
            except Exception:
                archived_lines.append(line)
                continue
            if ts >= cutoff:
                recent_lines.append(line)
            else:
                archived_lines.append(line)
    if archived_lines:
        archive = ANALYST_DIR / f"trade_log_{now_utc().strftime('%Y%m%d_%H%M%S')}.jsonl.gz"
        with gzip.open(archive, "wt", encoding="utf-8") as handle:
            handle.writelines(archived_lines)
    tmp = TRADE_LOG.with_name(f"{TRADE_LOG.name}.tmp.{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.writelines(recent_lines)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, TRADE_LOG)
    finally:
        if tmp.exists():
            tmp.unlink()


def run_analyst_loop(interval_seconds: int = 600) -> None:
    ensure_dirs()
    purge_demo_fixture_records()
    print("[ANALYST] KiBot Data Analyst started")
    while True:
        try:
            _update_daily_summary()
            rotate_logs_if_needed()
        except Exception as error:
            record_failure("kibot-analyst", "ANALYST_LOOP_ERROR", str(error), severity="WARNING")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    run_analyst_loop(ANALYST_INTERVAL_SECONDS)
