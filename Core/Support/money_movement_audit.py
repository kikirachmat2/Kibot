from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
import subprocess

from Core.Support.ki_config import STATE_DIR


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


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", False):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def load_state_bundle(state_dir: Path | None = None) -> Dict[str, Any]:
    state_dir = state_dir or STATE_DIR
    trade_history_rows: List[dict] = []
    trade_history_dir = state_dir / "trade_history"
    if trade_history_dir.exists():
        for file in sorted(trade_history_dir.glob("*.jsonl")):
            trade_history_rows.extend(_read_jsonl(file))
    return {
        "live_truth": _read_json(state_dir / "live_truth.json", {}),
        "no_trade_forensics": _read_json(state_dir / "no_trade_forensics.json", {}),
        "opportunity_funnel": _read_json(state_dir / "opportunity_funnel.json", {}),
        "candidate_decisions": _read_jsonl(state_dir / "candidate_decisions.jsonl"),
        "orders": _collect_json_files(state_dir / "orders"),
        "trade_history": trade_history_rows,
        "dust_positions": _read_json(state_dir / "dust_positions.json", []),
        "capital_governor": _read_json(state_dir / "capital_governor.json", {}),
        "risk_state": _read_json(state_dir / "risk_state.json", {}),
        "workflow": _read_json(state_dir / "workflow_automation.json", {}),
        "indodax_targets": _read_json(state_dir / "indodax_top_targets.json", {}),
        "phantom_targets": _read_json(state_dir / "phantom_top_targets.json", {}),
        "phantom_rpc_health": _read_json(state_dir / "phantom_rpc_health.json", {}),
        "server_telemetry": _read_json(state_dir / "server_telemetry.json", {}),
        "ai_patrol": _read_json(state_dir / "ai_patrol.json", {}),
        "ai_system_inventory": _read_json(state_dir / "ai_system_inventory.json", {}),
    }


def _collect_json_files(path: Path) -> List[dict]:
    rows: List[dict] = []
    if not path.exists():
        return rows
    for file in sorted(path.glob("*.json")):
        obj = _read_json(file, {})
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _count_rows(rows: Iterable[dict], *, key: str | None = None, values: Iterable[str] | None = None) -> int:
    if key is None:
        return sum(1 for row in rows if isinstance(row, dict))
    wanted = {str(v).upper() for v in (values or [])}
    return sum(1 for row in rows if str(row.get(key) or "").upper() in wanted)


def _count_in_window(rows: Iterable[dict], *, since_hours: int = 24, ts_keys: Tuple[str, ...] = ("ts", "timestamp", "updated_at", "timestamp_wib")) -> List[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    out: List[dict] = []
    for row in rows:
        dt = None
        for key in ts_keys:
            dt = _parse_dt(row.get(key))
            if dt is not None:
                break
        if dt is None and isinstance(row.get("ts"), (int, float)):
            dt = datetime.fromtimestamp(float(row["ts"]), timezone.utc)
        if dt is None:
            out.append(row)
        elif dt >= cutoff:
            out.append(row)
    return out


def money_movement_status(bundle: Dict[str, Any]) -> Dict[str, Any]:
    live_truth = bundle.get("live_truth", {})
    no_trade = bundle.get("no_trade_forensics", {})
    funnel = bundle.get("opportunity_funnel", {})
    candidate_decisions = bundle.get("candidate_decisions", [])
    trade_history = bundle.get("trade_history", [])
    orders = bundle.get("orders", [])
    dust_positions = bundle.get("dust_positions", [])
    capital = bundle.get("capital_governor", {})
    risk = bundle.get("risk_state", {})
    workflow = bundle.get("workflow", {})
    targets_indo = bundle.get("indodax_targets", {})
    targets_phantom = bundle.get("phantom_targets", {})
    rpc_health = bundle.get("phantom_rpc_health", {})

    live_fresh = bool(live_truth.get("updated_at"))
    canonical_state = str(no_trade.get("canonical_risk_state") or "UNKNOWN").upper()
    movement_status = str(no_trade.get("movement_status") or "").upper()
    if canonical_state in {"LOCKED", "EMERGENCY"} or movement_status == "LOCKED":
        status = "BLOCKED"
    elif live_fresh and movement_status in {"ACTIVE", "MICRO_PROBE_ALLOWED"}:
        status = "MOVING"
    elif live_fresh and movement_status in {"WAITING_FOR_A_PLUS", "HEALTHY_WAIT", "READY_BUT_WAITING"}:
        status = "READY_BUT_WAITING"
    elif not live_fresh:
        status = "BROKEN"
    else:
        status = "STUCK"

    c24 = _count_in_window(candidate_decisions)
    o24 = _count_in_window(orders)
    t24 = _count_in_window(trade_history)
    reason_counts = Counter()
    tier_counts = Counter()
    for row in c24:
        reason = str(row.get("reason") or row.get("wait_reason") or row.get("decision") or row.get("status") or "unknown")
        reason_counts[reason] += 1
        tier = str(row.get("tier") or row.get("trade_tier") or row.get("label") or "").upper()
        if tier:
            tier_counts[tier] += 1
    dominant_reason = reason_counts.most_common(1)[0][0] if reason_counts else ""
    last_trade = t24[-1] if t24 else {}
    last_trade_at = ""
    last_balance_change_at = ""
    if last_trade:
        last_trade_at = str(last_trade.get("timestamp_wib") or last_trade.get("updated_at") or "")
        last_balance_change_at = last_trade_at
    hours_since_last_trade = None
    if last_trade_at:
        dt = _parse_dt(last_trade_at)
        if dt:
            hours_since_last_trade = round((datetime.now(timezone.utc) - dt).total_seconds() / 3600.0, 2)

    result = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "money_movement_status": status,
        "primary_reason": dominant_reason or str(no_trade.get("movement_reason") or no_trade.get("why_wait") or "unknown"),
        "secondary_reasons": [r for r, _ in reason_counts.most_common(5)][1:],
        "last_balance_change_at": last_balance_change_at,
        "last_trade_at": last_trade_at,
        "hours_since_last_trade": hours_since_last_trade if hours_since_last_trade is not None else -1,
        "candidate_count_24h": len(c24),
        "a_plus_count_24h": tier_counts.get("A_PLUS", 0),
        "micro_probe_count_24h": tier_counts.get("MICRO_PROBE", 0),
        "approved_count_24h": sum(1 for row in c24 if bool(row.get("approved"))),
        "submitted_count_24h": _count_rows(o24, key="status", values={"SUBMITTED", "CREATED", "ORDER_SUBMITTED"}),
        "filled_count_24h": _count_rows(t24, key="status", values={"FILLED", "CLOSED", "RECONCILED"}),
        "dominant_rejection_reason": dominant_reason,
        "capital_bottleneck": any(token in dominant_reason.lower() for token in ("capital", "min_trade", "below_min_trade", "orders_disabled")),
        "min_trade_bottleneck": "below_min_trade" in dominant_reason.lower() or "min_trade" in dominant_reason.lower(),
        "ev_bottleneck": any(token in dominant_reason.upper() for token in ("EV", "EXPECTED_VALUE", "INSUFFICIENT_HISTORY")),
        "scanner_bottleneck": any(token in dominant_reason.lower() for token in ("scanner", "no_targets", "no_candidates", "strategy_no_edge")),
        "executor_bottleneck": any(token in dominant_reason.lower() for token in ("executor", "submitted", "filled", "dispatch")),
        "venue_bottleneck": bool(rpc_health) and str(rpc_health.get("status") or "").upper() not in {"OK", "HEALTHY", "RECONCILED"},
        "strategy_bottleneck": any(token in dominant_reason.lower() for token in ("strategy", "edge", "no_edge", "market")),
        "recommended_action": _recommend_action(status, dominant_reason, c24, o24, t24, no_trade, capital, workflow, targets_indo, targets_phantom, rpc_health),
        "live_truth": live_truth,
        "no_trade_forensics": no_trade,
        "opportunity_funnel": funnel,
        "candidate_decisions": c24,
        "trade_history": t24,
        "orders": o24,
        "dust_positions": dust_positions,
        "capital_governor": capital,
        "risk_state": risk,
        "workflow": workflow,
    }
    return result


def candidate_pipeline_audit(bundle: Dict[str, Any]) -> Dict[str, Any]:
    def _venue_block(venue: str, target_state: Dict[str, Any]) -> Dict[str, Any]:
        candidates = [row for row in bundle.get("candidate_decisions", []) if str(row.get("venue") or row.get("route") or "").lower().startswith(venue)]
        targets = target_state.get("top_targets", []) if isinstance(target_state, dict) else []
        approved = [row for row in candidates if bool(row.get("approved")) or str(row.get("tier") or "").upper() in {"A_PLUS", "MICRO_PROBE"}]
        submitted = [row for row in bundle.get("orders", []) if str(row.get("venue") or row.get("source") or "").lower().startswith(venue) and str(row.get("status") or "").upper() in {"SUBMITTED", "CREATED", "ORDER_SUBMITTED"}]
        filled = [row for row in bundle.get("trade_history", []) if str(row.get("venue") or row.get("source") or "").lower().startswith(venue) and str(row.get("status") or "").upper() in {"FILLED", "CLOSED", "RECONCILED"}]
        bottleneck = "NONE"
        if not _bool(bundle.get("server_telemetry", {}).get("cpu")):
            bottleneck = "SCANNER"
        elif targets and not candidates:
            bottleneck = "GATE"
        elif candidates and not approved:
            bottleneck = "GATE"
        elif approved and not submitted:
            bottleneck = "SIZE"
        elif submitted and not filled:
            bottleneck = "EXECUTOR"
        return {
            "scanner_active": bool(targets or candidates),
            "targets_count": len(targets),
            "candidate_decisions_count_24h": len(candidates),
            "tier_classifications_count_24h": len([row for row in candidates if row.get("tier") or row.get("trade_tier") or row.get("label")]),
            "approved_count_24h": len(approved),
            "submitted_count_24h": len(submitted),
            "filled_count_24h": len(filled),
            "bottleneck": bottleneck,
        }

    return {
        "indodax": _venue_block("indodax", bundle.get("indodax_targets", {})),
        "phantom": _venue_block("phantom", bundle.get("phantom_targets", {})),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _bool(value: Any) -> bool:
    return bool(value) and str(value).lower() not in {"false", "0", "none", ""}


def strategy_edge_audit(bundle: Dict[str, Any]) -> Dict[str, Any]:
    rows = bundle.get("trade_history", [])
    grouped: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for row in rows:
        venue = str(row.get("venue") or row.get("source") or "unknown").lower()
        pair = str(row.get("pair") or row.get("symbol") or "unknown").upper()
        grouped[(venue, pair)].append(row)
    strategies = []
    for (venue, pair), items in sorted(grouped.items()):
        net = sum(_as_float(i.get("net_realized_pnl_idr"), _as_float(i.get("realized_pnl_idr"), 0.0)) for i in items)
        gross = sum(_as_float(i.get("gross_realized_pnl_idr"), 0.0) for i in items)
        fee = sum(_as_float(i.get("fee_idr"), 0.0) for i in items)
        wins = [i for i in items if _as_float(i.get("net_realized_pnl_idr"), 0.0) > 0]
        losses = [i for i in items if _as_float(i.get("net_realized_pnl_idr"), 0.0) <= 0]
        sample = len(items)
        expectancy = net / sample if sample else 0.0
        status = "INSUFFICIENT_DATA" if sample < 30 else ("POSITIVE_EDGE" if net > 0 else "NEGATIVE_EDGE")
        recommendation = "COLLECT_MICRO_PROBE" if sample < 30 else ("SCALE_UP" if net > 0 else "DISABLE")
        strategies.append(
            {
                "venue": venue,
                "strategy": pair,
                "sample_size": sample,
                "net_pnl_idr": round(net, 2),
                "gross_pnl_idr": round(gross, 2),
                "fees_idr": round(fee, 2),
                "win_rate": round(len(wins) / sample, 4) if sample else None,
                "avg_win_idr": round(sum(_as_float(i.get("net_realized_pnl_idr"), 0.0) for i in wins) / len(wins), 2) if wins else 0.0,
                "avg_loss_idr": round(sum(_as_float(i.get("net_realized_pnl_idr"), 0.0) for i in losses) / len(losses), 2) if losses else 0.0,
                "expectancy_idr": round(expectancy, 2),
                "profit_factor": round(sum(_as_float(i.get("net_realized_pnl_idr"), 0.0) for i in wins) / abs(sum(_as_float(i.get("net_realized_pnl_idr"), 0.0) for i in losses)), 4) if losses and sum(_as_float(i.get("net_realized_pnl_idr"), 0.0) for i in losses) != 0 else None,
                "status": status,
                "recommendation": recommendation,
            }
        )
    return {"updated_at": datetime.now(timezone.utc).isoformat(), "strategies": strategies}


def ai_support_audit(bundle: Dict[str, Any]) -> Dict[str, Any]:
    inv = bundle.get("ai_system_inventory", {})
    patrol = bundle.get("ai_patrol", {})
    providers = bundle.get("provider_health", {})
    sources = bundle.get("source_health", {})
    status = "OK" if inv and patrol else "WARN"
    if not inv or not patrol:
        status = "FAIL" if not inv else "WARN"
    can_place_order = False
    can_override = False
    latest = str(patrol.get("support_action") or patrol.get("decision_state") or patrol.get("status") or "")
    issues = []
    if not inv:
        issues.append("inventory_missing")
    if not patrol:
        issues.append("patrol_missing")
    if isinstance(inv, dict):
        for cat in inv.get("categories", {}).values() if isinstance(inv.get("categories"), dict) else []:
            for item in cat if isinstance(cat, list) else []:
                if item.get("can_place_order"):
                    can_place_order = True
                if item.get("can_override_gate"):
                    can_override = True
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "ai_health": status,
        "can_place_order": can_place_order,
        "can_override_gate": can_override,
        "latest_advisory": latest,
        "issues": issues,
        "providers": providers,
        "sources": sources,
    }


def server_support_audit(bundle: Dict[str, Any]) -> Dict[str, Any]:
    telemetry = bundle.get("server_telemetry", {})
    no_trade = bundle.get("no_trade_forensics", {}) or {}
    services_ok = False
    try:
        res = subprocess.run(["systemctl", "is-active", "kibot-master", "kibot-scanner", "kibot-executor", "kibot-dashboard", "kibot-live-truth", "kibot-workflow-supervisor"], capture_output=True, text=True, timeout=20, check=False)
        services_ok = "active" in (res.stdout or "")
    except Exception:
        services_ok = False
    backups_root = STATE_DIR.parent / "backups" / "state"
    backups_ok = bool(backups_root.exists())
    latest_backup_age_s = -1.0
    if backups_ok:
        try:
            backups = sorted([p for p in backups_root.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
            if backups:
                latest_backup_age_s = round(datetime.now(timezone.utc).timestamp() - backups[0].stat().st_mtime, 1)
                backups_ok = latest_backup_age_s <= 21600.0
        except Exception:
            backups_ok = False
    stale_ok = not bool(no_trade.get("ignored_stale_blockers"))
    status = "OK" if services_ok and telemetry and backups_ok and stale_ok else "WARN"
    if not telemetry or not services_ok:
        status = "FAIL"
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "server_support_status": status,
        "services_ok": services_ok,
        "telemetry": telemetry,
        "stale_guards": stale_ok,
        "backups": backups_ok,
        "latest_backup_age_s": latest_backup_age_s,
        "watchdog": True,
        "errors": [],
    }


def _recommend_action(status: str, dominant_reason: str, candidates: List[dict], orders: List[dict], trades: List[dict], no_trade: Dict[str, Any], capital: Dict[str, Any], workflow: Dict[str, Any], targets_indo: Dict[str, Any], targets_phantom: Dict[str, Any], rpc_health: Dict[str, Any]) -> str:
    if status == "BROKEN":
        return "repair runtime freshness / services"
    if status == "BLOCKED":
        return "inspect canonical blockers and wait or unlock stale blockers"
    if status == "READY_BUT_WAITING":
        if "EV_SAMPLE_TOO_SMALL" in dominant_reason.upper() or "INSUFFICIENT_HISTORY" in dominant_reason.upper():
            return "allow micro-probe for safe candidates"
        if "below_min_trade" in dominant_reason.lower():
            return "increase viable universe or reduce min trade only if execution-safe"
        return "continue scan and allow A_PLUS when ready"
    if status == "MOVING":
        return "monitor fills and preserve risk discipline"
    if not candidates and (targets_indo or targets_phantom):
        return "candidate pipeline likely broken; inspect tier classifier integration"
    if not candidates:
        return "widen safe universe and keep scanning"
    if orders and not trades:
        return "executor or fill bottleneck; check pricing and order tracker"
    return "continue scanning and evaluating opportunities"
