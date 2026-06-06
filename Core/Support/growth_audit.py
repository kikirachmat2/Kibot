from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from Core.Support.ki_config import STATE_DIR
from Core.Support.churn_guard import evaluate_churn_guard
from Core.Support.money_movement_audit import _as_float, _parse_dt, load_state_bundle
from Core.Support.round_trip_accounting import build_round_trip_accounting
from Core.Support.recovery_mode_policy import build_recovery_mode_policy


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


def _ensure_state_dir(path: Path | None = None) -> Path:
    state_dir = path or STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def _trade_rows(state_dir: Path | None = None) -> List[dict]:
    state_dir = state_dir or STATE_DIR
    rows: List[dict] = []
    trade_dir = state_dir / "trade_history"
    if trade_dir.exists():
        for file in sorted(trade_dir.glob("*.jsonl")):
            rows.extend(_read_jsonl(file))
    rows.extend(_read_jsonl(state_dir / "trade_log.jsonl"))
    return rows


def _bundle_trade_rows(bundle: Dict[str, Any] | None = None) -> List[dict]:
    if bundle and isinstance(bundle.get("trade_history"), list) and bundle.get("trade_history"):
        return [row for row in bundle.get("trade_history", []) if isinstance(row, dict)]
    return _trade_rows()


def _in_window(rows: Iterable[dict], hours: int = 24) -> List[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out: List[dict] = []
    for row in rows:
        dt = None
        for key in ("timestamp_wib", "updated_at", "timestamp", "ts", "created_at"):
            dt = _parse_dt(row.get(key))
            if dt is not None:
                break
        if dt is None and isinstance(row.get("timestamp"), (int, float)):
            dt = datetime.fromtimestamp(float(row["timestamp"]), timezone.utc)
        if dt is None:
            out.append(row)
        elif dt >= cutoff:
            out.append(row)
    return out


def _normalize_pair(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    raw = raw.replace("-", "_").replace("/", "_")
    raw = raw.replace("__", "_")
    if raw.endswith("IDR") and not raw.endswith("_IDR"):
        raw = raw[:-3] + "_IDR"
    return raw


def _fill_rows(rows: Iterable[dict]) -> List[dict]:
    out = []
    for row in rows:
        et = str(row.get("event_type") or row.get("trade_event_type") or "").upper()
        st = str(row.get("status") or "").upper()
        side = str(row.get("side") or "").upper()
        if et in {"ORDER_FILLED", "FILL", "FILLED"} or st in {"FILLED", "CLOSED", "RECONCILED"} or side in {"BUY", "SELL"}:
            out.append(row)
    return out


def _order_rows(rows: Iterable[dict]) -> List[dict]:
    out = []
    for row in rows:
        et = str(row.get("event_type") or row.get("trade_event_type") or "").upper()
        st = str(row.get("status") or "").upper()
        if et in {"ORDER_CREATED", "ORDER_SUBMITTED", "ORDER_CANCELLED", "ORDER_REJECTED", "ORDER_FILLED"} or st in {"CREATED", "SUBMITTED", "CANCELLED", "REJECTED", "FILLED"}:
            out.append(row)
    return out


def _trade_equity_snapshot(bundle: Dict[str, Any]) -> float:
    live_truth = bundle.get("live_truth", {})
    if isinstance(live_truth, dict) and live_truth:
        return _as_float(live_truth.get("wallet_equity_idr"), _as_float(live_truth.get("total_equity_idr"), 0.0))
    capital = bundle.get("capital_governor", {})
    if isinstance(capital, dict):
        return _as_float(capital.get("current_total_equity_idr"), 0.0)
    return 0.0


def build_critical_operator_questions(bundle: Dict[str, Any] | None = None) -> Dict[str, Any]:
    bundle = bundle or load_state_bundle()
    trade_rows = _in_window(_bundle_trade_rows(bundle))
    fill_rows = _fill_rows(trade_rows)
    order_rows = _order_rows(trade_rows)
    closed_round_trips = [r for r in trade_rows if str(r.get("event_type") or "").upper() in {"POSITION_CLOSED", "ROUND_TRIP_CLOSED", "ORDER_FILLED"} and str(r.get("side") or "").upper() == "SELL"]
    questions = [
        {"id": "moving_or_growing", "question": "Is the system actually growing net equity, or only generating fills?", "answer": "GROWING" if _trade_equity_snapshot(bundle) > 0 and len(fill_rows) > 0 else "UNCLEAR"},
        {"id": "indodax_net_pnl_after_costs", "question": "If Indodax has 50 fills in 24h, what is the net PnL after fee/spread/slippage?", "answer": "Use net-growth audit; current evidence suggests movement with likely churn if net equity delta stays flat."},
        {"id": "avg_pnl_per_fill", "question": "What is average PnL per fill?", "answer": str(round((_trade_equity_snapshot(bundle) - _as_float(bundle.get('capital_governor', {}).get('start_total_equity_idr'), 0.0)) / max(len(fill_rows), 1), 2))},
        {"id": "avg_fee_per_fill", "question": "What is average fee per fill?", "answer": "Need fee-trace reconciliation from trade history; current state lacks a clean per-fill fee ledger."},
        {"id": "gross_vs_net", "question": "What is gross PnL vs net PnL?", "answer": "Use accounting_truth and trade_history; net is the decision metric."},
        {"id": "fills_type", "question": "Are fills mostly entries, exits, partial fills, cancel/retry artifacts, or real closed round trips?", "answer": "Requires fill-quality audit; current indicators suggest many fills but not enough closed round trips."},
        {"id": "indodax_overtrading", "question": "Is Indodax overtrading?", "answer": "Possible if fill count high and net growth flat/negative."},
        {"id": "micro_probe_churn", "question": "Is micro-probe causing churn?", "answer": "Possible if many fills but low closed round-trip profit."},
        {"id": "a_plus_rarity", "question": "Is A_PLUS too rare?", "answer": "Possibly, but that is safer than forcing weak trades."},
        {"id": "micro_probe_loose", "question": "Is MICRO_PROBE too strict or too loose?", "answer": "Current evidence suggests it may be too loose on count and too strict on conversion quality."},
        {"id": "symbol_mapping", "question": "Are strategy edge stats based on clean symbol mapping?", "answer": "No, EDEN_IDR vs EDEN/IDR contradiction indicates normalization issues."},
        {"id": "eden_contradiction", "question": "Why does EDEN_IDR show NEGATIVE_EDGE but EDEN/IDR unknown-source shows POSITIVE_EDGE?", "answer": "Symbol/source normalization issue until proven otherwise."},
        {"id": "different_symbols", "question": "Are EDEN_IDR and EDEN/IDR treated as different symbols?", "answer": "Currently likely yes in some reports; needs normalization patch."},
        {"id": "unknown_source", "question": "Is the 'unknown-source' edge row reliable or should it be ignored?", "answer": "Ignore for scale-up unless source is verified."},
        {"id": "pha_pond_noise", "question": "Are PHA/POND actually candidates worth micro-probing, or just insufficient noisy data?", "answer": "Treat as insufficient noisy data until more clean samples exist."},
        {"id": "negative_edge_disable", "question": "Are negative-edge pairs disabled in live scanner or only reported?", "answer": "Need policy enforcement; report alone is not enough."},
        {"id": "below_min_trade", "question": "Is below_min_trade still occurring?", "answer": "Likely yes on some sizing paths when probe sizing is too small."},
        {"id": "daily_controls", "question": "Does daily loss cap/profit lock/max trades block trades today?", "answer": str(bundle.get("capital_governor", {}).get("allow_new_orders_reason") or "unknown")},
        {"id": "max_trades", "question": "Does max trades/day allow movement but prevent overtrading?", "answer": "It should, but verify against net growth audit."},
        {"id": "stale_guards", "question": "Are stale guards really false? If so, why is server support OK?", "answer": "Server support should degrade if stale guards/backups are false."},
        {"id": "backups", "question": "Are backups false? If so, why is live-money system considered OK?", "answer": "It should not be considered fully OK until backups pass."},
        {"id": "biggest_problem", "question": "What is the single biggest problem preventing net growth?", "answer": "Likely fee/spread churn plus stale or conflicting accounting and gate/data mapping."},
        {"id": "first_fix", "question": "If you had full control, what would you change first: strategy, risk, scanner, execution, accounting, or server support?", "answer": "Accounting + fill-quality + strategy symbol normalization first, then strategy/risk tuning."},
    ]
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "questions": questions,
        "summary": {
            "fills_24h": len(fill_rows),
            "orders_24h": len(order_rows),
            "closed_round_trips_24h": len(closed_round_trips),
            "equity_idr": _trade_equity_snapshot(bundle),
        },
    }
    state_path = _ensure_state_dir() / "critical_operator_questions.json"
    state_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def _window_stats(rows: List[dict], key: str) -> float:
    if not rows:
        return 0.0
    return sum(_as_float(row.get(key), 0.0) for row in rows)


def audit_net_growth(bundle: Dict[str, Any] | None = None) -> Dict[str, Any]:
    bundle = bundle or load_state_bundle()
    state_dir = _ensure_state_dir()
    live_truth = bundle.get("live_truth", {})
    capital = bundle.get("capital_governor", {})
    accounting = bundle.get("accounting_truth", {})
    no_trade = bundle.get("no_trade_forensics", {})
    round_trip_payload = build_round_trip_accounting(bundle)
    round_trip_stats = round_trip_payload.get("stats", {}) if isinstance(round_trip_payload, dict) else {}

    trade_rows = _in_window(_bundle_trade_rows(bundle))
    fill_rows = _fill_rows(trade_rows)
    order_rows = _order_rows(trade_rows)
    closed_round_trips = round_trip_payload.get("closed_round_trips", []) if isinstance(round_trip_payload, dict) else []
    open_round_trips = round_trip_payload.get("open_round_trips", []) if isinstance(round_trip_payload, dict) else []
    fills_24h = len(fill_rows)
    orders_24h = len(order_rows)
    cancels_24h = sum(1 for row in order_rows if str(row.get("status") or "").upper() == "CANCELLED" or str(row.get("event_type") or "").upper() == "ORDER_CANCELLED")
    partial_fills_24h = sum(1 for row in fill_rows if _as_float(row.get("filled_amount_coin") or row.get("partial_fill_ratio"), 0.0) not in {0.0, 1.0} or "PARTIAL" in str(row.get("status") or "").upper())
    grouped: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for row in fill_rows:
        venue = str(row.get("venue") or row.get("source") or "unknown").lower()
        pair = _normalize_pair(row.get("pair") or row.get("symbol"))
        grouped[(venue, pair)].append(row)

    round_trips = len(closed_round_trips)
    gross_pnl = sum(_as_float(r.get("gross_pnl_idr"), 0.0) for r in closed_round_trips)
    net_pnl = sum(_as_float(r.get("net_pnl_idr"), 0.0) for r in closed_round_trips)
    fees = sum(_as_float(r.get("fees_idr"), 0.0) for r in closed_round_trips)
    wins = sum(1 for r in closed_round_trips if _as_float(r.get("net_pnl_idr"), 0.0) > 0)
    losses = sum(1 for r in closed_round_trips if _as_float(r.get("net_pnl_idr"), 0.0) <= 0)
    per_trip = [_as_float(r.get("net_pnl_idr"), 0.0) for r in closed_round_trips]

    total_equity = _as_float((live_truth or {}).get("total_equity_idr"), _as_float(accounting.get("current_total_equity_idr"), 0.0))
    start_equity = _as_float((capital or {}).get("start_total_equity_idr"), _as_float(accounting.get("start_total_equity_idr"), total_equity))
    equity_change = total_equity - start_equity
    equity_change_pct = (equity_change / max(start_equity, 1.0)) * 100.0
    slippage_est = max(0.0, abs(gross_pnl) * 0.05)
    spread_cost_est = max(0.0, abs(gross_pnl) * 0.03)
    avg_round_trip = net_pnl / round_trips if round_trips else 0.0
    avg_fill = net_pnl / fills_24h if fills_24h else 0.0
    max_drawdown = abs(min(0.0, _as_float((capital or {}).get("daily_pnl_idr"), 0.0)))
    dust_positions = bundle.get("dust_positions", []) or []
    dust_value = sum(_as_float(row.get("value_idr") or row.get("cost_idr") or row.get("amount_idr"), 0.0) for row in dust_positions if isinstance(row, dict))

    status = "INSUFFICIENT_DATA"
    churn = False
    churn_reason = ""
    if round_trips == 0:
        status = "NO_CLOSED_ROUND_TRIPS"
        churn_reason = "no_closed_round_trips"
    else:
        if net_pnl > 0 and net_pnl > fees + slippage_est + spread_cost_est:
            status = "GROWING"
        elif abs(net_pnl) <= max(1000.0, fees + slippage_est + spread_cost_est):
            status = "FLAT_CHURN"
            churn = True
            churn_reason = "fills_present_but_net_pnl_flat_or_costs_dominate"
        else:
            status = "LOSING"
            churn = True
            churn_reason = "net_pnl_negative_after_costs"
    if not live_truth or not isinstance(live_truth, dict):
        status = "ACCOUNTING_UNCLEAR"
        churn_reason = "live_truth_missing"

    profit_factor = None
    if per_trip:
        gains = sum(v for v in per_trip if v > 0)
        losses_abs = abs(sum(v for v in per_trip if v <= 0))
        if losses_abs > 0:
            profit_factor = round(gains / losses_abs, 4)
    win_rate = round(wins / round_trips, 4) if round_trips else None
    if status == "GROWING":
        recommendation = "continue cautiously; preserve net edge and avoid scaling unknown sources"
    elif status == "FLAT_CHURN":
        recommendation = "reduce frequency, widen cost filters, and cut duplicate/micro-probe churn"
    elif status == "LOSING":
        recommendation = "lock new entries until edge, symbol mapping, and fill quality improve"
    elif status == "ACCOUNTING_UNCLEAR":
        recommendation = "repair accounting truth before any scale decision"
    else:
        recommendation = "collect more closed round trips before scaling"

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "total_equity_idr": total_equity,
        "equity_change_24h_idr": round(equity_change, 2),
        "equity_change_24h_pct": round(equity_change_pct, 4),
        "gross_pnl_24h_idr": round(gross_pnl, 2),
        "fees_24h_idr": round(fees, 2),
        "slippage_est_24h_idr": round(slippage_est, 2),
        "spread_cost_est_24h_idr": round(spread_cost_est, 2),
        "net_pnl_24h_idr": round(net_pnl, 2),
        "realized_pnl_24h_idr": round(net_pnl, 2),
        "unrealized_pnl_24h_idr": _as_float((live_truth or {}).get("unrealized_pnl_idr"), 0.0),
        "closed_round_trips_24h": round_trips,
        "fills_24h": fills_24h,
        "orders_24h": orders_24h,
        "cancels_24h": cancels_24h,
        "partial_fills_24h": partial_fills_24h,
        "avg_net_pnl_per_round_trip_idr": round(avg_round_trip, 2),
        "avg_net_pnl_per_fill_idr": round(avg_fill, 2),
        "profit_factor": profit_factor,
        "win_rate": win_rate,
        "max_drawdown_24h_idr": round(max_drawdown, 2),
        "dust_value_idr": round(dust_value, 2),
        "is_churning": churn,
        "churn_reason": churn_reason,
        "recommendation": recommendation,
        "round_trip_accounting": round_trip_payload,
        "round_trip_stats": round_trip_stats,
        "open_round_trips_24h": len(open_round_trips),
    }
    (state_dir / "net_growth_audit.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    build_critical_operator_questions(bundle)
    return payload


def audit_fill_quality(bundle: Dict[str, Any] | None = None) -> Dict[str, Any]:
    bundle = bundle or load_state_bundle()
    trade_rows = _in_window(_bundle_trade_rows(bundle))
    fill_rows = _fill_rows(trade_rows)
    round_trip_payload = build_round_trip_accounting(bundle)
    canonical_closed = round_trip_payload.get("closed_round_trips", []) if isinstance(round_trip_payload, dict) else []
    canonical_open = round_trip_payload.get("open_round_trips", []) if isinstance(round_trip_payload, dict) else []
    canonical_stats = round_trip_payload.get("stats", {}) if isinstance(round_trip_payload, dict) else {}
    pair_counts = Counter(_normalize_pair(row.get("pair") or row.get("symbol")) for row in fill_rows)
    duplicates = sum(count - 1 for count in pair_counts.values() if count > 1)
    micro_probe = sum(1 for row in fill_rows if "MICRO" in str(row.get("tier") or row.get("label") or row.get("reason") or "").upper())
    a_plus = sum(1 for row in fill_rows if "A_PLUS" in str(row.get("tier") or row.get("label") or "").upper())
    closed_round_trips = len(canonical_closed)
    open_round_trips = len(canonical_open)
    avg_size = sum(_as_float(row.get("amount_idr") or row.get("budget_idr") or row.get("notional_idr"), 0.0) for row in fill_rows) / max(len(fill_rows), 1)
    avg_hold = 0.0
    fee_drag = sum(_as_float(row.get("fee_idr"), 0.0) for row in fill_rows)
    fee_drag_pct = (fee_drag / max(sum(_as_float(row.get("gross_realized_pnl_idr"), 0.0) for row in fill_rows) + fee_drag, 1.0)) * 100.0
    status = "CLEAN"
    source_quality = "RAW_FILL_ONLY"
    warning = ""
    if duplicates > 0 and len(fill_rows) > 0:
        status = "DUPLICATE_COUNTING"
    if micro_probe > len(fill_rows) * 0.5:
        status = "CHURN"
    if closed_round_trips > 0:
        source_quality = "CANONICAL_ROUND_TRIP"
    if closed_round_trips > 0 and len(fill_rows) == 0:
        status = "CANONICAL_ROUND_TRIP_AVAILABLE"
        warning = "raw_fill_source_missing"
        source_quality = "CANONICAL_ROUND_TRIP"
    elif closed_round_trips == 0:
        if len(fill_rows) > 0:
            status = "NO_CLOSED_ROUND_TRIPS"
        else:
            status = "ACCOUNTING_REPAIR_REQUIRED"
            source_quality = "INCOMPLETE"
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "filled_count_24h_reported": len(fill_rows),
        "real_fills_detected": len(fill_rows) if len(fill_rows) > 0 else closed_round_trips,
        "closed_round_trips": closed_round_trips,
        "open_round_trips": open_round_trips,
        "entries": sum(1 for row in fill_rows if str(row.get("side") or "").upper() == "BUY"),
        "exits": sum(1 for row in fill_rows if str(row.get("side") or "").upper() == "SELL"),
        "partial_fills": sum(1 for row in fill_rows if "PARTIAL" in str(row.get("status") or "").upper()),
        "duplicates_suspected": duplicates,
        "micro_probe_fills": micro_probe,
        "a_plus_fills": a_plus,
        "avg_size_idr": round(avg_size, 2),
        "avg_hold_minutes": avg_hold,
        "avg_net_pnl_idr": round(sum(_as_float(row.get("net_realized_pnl_idr"), 0.0) for row in fill_rows) / max(len(fill_rows), 1), 2),
        "fee_drag_pct": round(fee_drag_pct, 2),
        "status": status,
        "source_quality": source_quality,
        "warning": warning,
        "round_trip_accounting": round_trip_payload,
        "recovery_mode_policy": build_recovery_mode_policy(bundle),
        "churn_guard": evaluate_churn_guard(bundle),
        "canonical_stats": canonical_stats,
    }
    (_ensure_state_dir() / "fill_quality_audit.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def audit_strategy_symbol_normalization(bundle: Dict[str, Any] | None = None) -> Dict[str, Any]:
    bundle = bundle or load_state_bundle()
    rows = bundle.get("trade_history", [])
    normalized: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        pair = _normalize_pair(row.get("pair") or row.get("symbol"))
        if pair:
            normalized[pair].append(row)
    eden_rows = normalized.get("EDEN_IDR", [])
    unknown_eden = [row for row in rows if _normalize_pair(row.get("pair") or row.get("symbol")) == "EDEN_IDR" and str(row.get("source") or "").lower() == "unknown"]
    pos = sum(1 for row in eden_rows if _as_float(row.get("net_realized_pnl_idr"), _as_float(row.get("realized_pnl_idr"), 0.0)) > 0)
    neg = sum(1 for row in eden_rows if _as_float(row.get("net_realized_pnl_idr"), _as_float(row.get("realized_pnl_idr"), 0.0)) <= 0)
    reliable = len(unknown_eden) == 0
    recommendation = "DISABLE" if neg > pos else "SCALE" if reliable else "IGNORE_UNKNOWN_SOURCE_SCALE_UP"
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "canonical_map": {
            "EDEN_IDR": ["EDEN_IDR", "EDEN/IDR", "eden_idr", "EDENIDR"],
            "XRP_IDR": ["XRP_IDR", "XRP/IDR", "xrp_idr", "XRPIDR"],
            "POND_IDR": ["POND_IDR", "POND/IDR", "pond_idr", "PONDIDR"],
        },
        "eden": {
            "count": len(eden_rows),
            "positive": pos,
            "negative": neg,
            "unknown_source_count": len(unknown_eden),
            "reliable": reliable,
            "recommendation": recommendation,
        },
        "unknown_source_scale_up_safe": False,
        "normalized_positive_pairs": [
            pair for pair, items in normalized.items() if sum(1 for row in items if _as_float(row.get("net_realized_pnl_idr"), _as_float(row.get("realized_pnl_idr"), 0.0)) > 0) > sum(1 for row in items if _as_float(row.get("net_realized_pnl_idr"), _as_float(row.get("realized_pnl_idr"), 0.0)) <= 0)
        ],
    }
    (_ensure_state_dir() / "strategy_symbol_normalization_audit.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def audit_daily_controls(bundle: Dict[str, Any] | None = None) -> Dict[str, Any]:
    bundle = bundle or load_state_bundle()
    capital = bundle.get("capital_governor", {})
    no_trade = bundle.get("no_trade_forensics", {})
    controls = bundle.get("workflow", {})
    recovery = build_recovery_mode_policy(bundle)
    churn = evaluate_churn_guard(bundle)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "daily_loss_cap": _as_float(capital.get("max_daily_loss_idr"), 0.0),
        "profit_lock": bool(capital.get("daily_profit_lock") or capital.get("profit_lock")),
        "max_trades_per_day": _as_float(capital.get("max_trades_per_day"), 0.0),
        "max_micro_probes_per_day": _as_float((no_trade.get("micro_probe") or {}).get("remaining_today"), 0.0),
        "max_consecutive_losses": _as_float(capital.get("max_consecutive_losses"), 0.0),
        "fee_budget_idr": _as_float(capital.get("fee_budget_idr"), 0.0),
        "no_new_entry_time": str(capital.get("no_new_entry_time") or ""),
        "caused_freeze": bool(capital.get("global_hard_stop")) or str(capital.get("status") or "").upper().startswith("BLOCKED"),
        "allowed_churn": bool(bundle.get("money_movement_status") == "MOVING" and _as_float(capital.get("daily_pnl_idr"), 0.0) == 0.0),
        "recommendation": "TIGHTEN" if bool(capital.get("allow_new_orders")) is False and _as_float(capital.get("daily_pnl_idr"), 0.0) < 0 else "KEEP",
        "raw": {
            "controls_status": str(controls.get("overall_status") or ""),
        },
        "recovery_mode_policy": recovery,
        "churn_guard": churn,
    }
    (_ensure_state_dir() / "daily_controls_audit.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def assert_stale_guard_state(bundle: Dict[str, Any] | None = None) -> Dict[str, Any]:
    bundle = bundle or load_state_bundle()
    live_truth = bundle.get("live_truth", {})
    workflow = bundle.get("workflow", {})
    scanner = _read_json(STATE_DIR / "scanner_runtime.json", {})
    executor = _read_json(STATE_DIR / "indodax_executor_state.json", {})
    ages = {
        "live_truth": live_truth.get("updated_at") or live_truth.get("timestamp"),
        "workflow": workflow.get("updated_at") or workflow.get("timestamp"),
        "scanner": scanner.get("updated_at") or scanner.get("timestamp"),
        "executor": executor.get("updated_at") or executor.get("timestamp"),
    }
    fresh = bool(ages["live_truth"]) and bool(ages["workflow"]) and bool(ages["scanner"]) and bool(ages["executor"])
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "fresh": fresh,
        "ages": ages,
    }
    (_ensure_state_dir() / "stale_guard_state.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload
