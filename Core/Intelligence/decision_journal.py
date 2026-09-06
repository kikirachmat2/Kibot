"""Structured decision journal for KiBot trading intelligence.

This module is intentionally lightweight: JSONL files are easy to inspect,
replay, and ship to dashboards without introducing a heavy database first.
It implements the data-capture contracts from TRADING_STRATEGY.md.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = ROOT / "state"
JOURNAL_DIR = STATE_DIR / "decision_journal"
WIB = timezone(timedelta(hours=int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7"))))


def _now_wib() -> datetime:
    return datetime.now(WIB)


def _json_default(value: Any) -> str:
    return str(value)


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=True, default=_json_default) + "\n")


def _compact_signal(signal: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(signal, dict):
        return {}
    keep = [
        "symbol",
        "exchange",
        "price",
        "confidence",
        "opportunity_score",
        "lifecycle",
        "pump_stage",
        "trade_grade",
        "entry_quality",
        "exit_quality",
        "spread_pct",
        "vol_ratio",
        "change_5m_pct",
        "change_pct",
        "runup_24h_proxy_pct",
        "distance_to_high_pct",
        "historian_profile",
        "confidence_breakdown",
        "freshness",
    ]
    return {key: signal.get(key) for key in keep if key in signal}


def log_event(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Append a structured intelligence event and return the final record."""
    now = _now_wib()
    record = {
        "event_type": str(event_type).upper(),
        "ts": time.time(),
        "timestamp_wib": now.isoformat(),
        "date_wib": now.date().isoformat(),
        **(payload or {}),
    }
    _append_jsonl(JOURNAL_DIR / f"{now.date().isoformat()}.jsonl", record)
    return record


def log_scanner_candidates(candidates: Iterable[Dict[str, Any]], *, context: Optional[Dict[str, Any]] = None) -> None:
    rows = [_compact_signal(row) for row in list(candidates or [])[:25] if isinstance(row, dict)]
    if not rows:
        return
    log_event("SCANNER_CANDIDATES", {
        "candidate_count": len(rows),
        "top_candidates": rows[:10],
        "context": context or {},
    })


def log_council_decision(decision: Dict[str, Any]) -> None:
    if not isinstance(decision, dict):
        return
    source_signal = _compact_signal(decision.get("source_signal") or {})
    log_event("COUNCIL_DECISION", {
        "decision_state": decision.get("decision_state"),
        "status": decision.get("status"),
        "action": decision.get("action"),
        "ticker": decision.get("ticker"),
        "confidence": decision.get("confidence"),
        "decision_score": decision.get("decision_score"),
        "enter_score": decision.get("enter_score"),
        "wait_score": decision.get("wait_score"),
        "exit_score": decision.get("exit_score"),
        "deadline_mode": decision.get("deadline_mode") or (decision.get("daily_context") or {}).get("deadline_mode"),
        "daily_context": decision.get("daily_context"),
        "source_signal": source_signal,
        "wait_reason": decision.get("wait_reason") or decision.get("recovery_reason"),
        "confidence_floor": decision.get("confidence_floor"),
        "evidence_bundle": decision.get("evidence_bundle"),
        "role_votes": decision.get("role_votes"),
    })


def log_execution_event(event_type: str, payload: Dict[str, Any]) -> None:
    log_event(f"EXECUTOR_{event_type}", payload)


def log_pre_trade_simulation(simulation: Dict[str, Any]) -> None:
    log_event("PRE_TRADE_SIMULATION", simulation)


def log_missed_opportunity(opportunity: Dict[str, Any]) -> None:
    log_event("MISSED_OPPORTUNITY", opportunity)


def log_ai_accuracy(role: str, accuracy_data: Dict[str, Any]) -> None:
    log_event("AI_ACCURACY", {
        "role": role,
        **accuracy_data
    })


def log_rejected_candidate(candidate: Dict[str, Any], reason: str, context: Optional[Dict[str, Any]] = None) -> None:
    """Log a candidate that was rejected by the Council or RiskGate."""
    payload = {
        "candidate": candidate,
        "reason": reason,
        "context": context or {}
    }
    log_event("REJECTED_CANDIDATE", payload)


def read_today_events(limit: int = 500) -> List[Dict[str, Any]]:
    path = JOURNAL_DIR / f"{_now_wib().date().isoformat()}.jsonl"
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


def summarize_today() -> Dict[str, Any]:
    rows = read_today_events(limit=5000)
    summary = {
        "event_count": len(rows),
        "scanner_batches": 0,
        "council_decisions": 0,
        "trade_events": 0,
        "trade_opens": 0,
        "trade_closes": 0,
        "entries": 0,
        "waits": 0,
        "exits": 0,
        "pre_trade_pass": 0,
        "pre_trade_reject": 0,
        "rejected_candidates": 0,
        "missed_opportunities": 0,
        "best_missed_opportunity": None,
        "ai_accuracy_events": 0,
        "top_candidates": [],
        "latest_decision": None,
        "latest_trade_event": None,
        "realized_trade_pnl_idr": 0.0,
    }
    top_candidates: List[Dict[str, Any]] = []
    for row in rows:
        et = row.get("event_type")
        if et == "SCANNER_CANDIDATES":
            summary["scanner_batches"] += 1
            top_candidates.extend(row.get("top_candidates") or [])
        elif et == "COUNCIL_DECISION":
            summary["council_decisions"] += 1
            summary["latest_decision"] = row
            state = str(row.get("decision_state") or "").upper()
            if state == "ENTER":
                summary["entries"] += 1
            elif state == "EXIT":
                summary["exits"] += 1
            else:
                summary["waits"] += 1
        elif et == "PRE_TRADE_SIMULATION":
            if row.get("passed"):
                summary["pre_trade_pass"] += 1
            else:
                summary["pre_trade_reject"] += 1
        elif et == "MISSED_OPPORTUNITY":
            summary["missed_opportunities"] += 1
            if not summary["best_missed_opportunity"] or row.get("pnl_pct", 0) > summary["best_missed_opportunity"].get("pnl_pct", 0):
                summary["best_missed_opportunity"] = row
        elif et == "AI_ACCURACY":
            summary["ai_accuracy_events"] += 1
        elif et == "REJECTED_CANDIDATE":
            summary["rejected_candidates"] += 1
        elif et == "SIGNAL_DROPPED_BUSY":
            summary["signals_dropped_busy"] = summary.get("signals_dropped_busy", 0) + 1
        elif et == "TRADE_EVENT" or str(row.get("trade_event_type") or "").strip():
            summary["trade_events"] += 1
            summary["latest_trade_event"] = row
            trade_kind = str(row.get("trade_event_type") or row.get("kind") or "").upper()
            if not trade_kind:
                trade_kind = str(row.get("event_type") or "").upper()
            if trade_kind in {"ORDER_FILLED", "POSITION_OPENED", "BUY_FILLED"}:
                summary["trade_opens"] += 1
            elif trade_kind in {"ORDER_RECONCILED", "POSITION_CLOSED", "SELL_FILLED"}:
                summary["trade_closes"] += 1
                summary["realized_trade_pnl_idr"] += float(row.get("realized_pnl_idr") or 0.0)
    # Deduplicate candidates by symbol, keeping the highest score / latest entry
    cand_by_sym: Dict[str, Dict[str, Any]] = {}
    for cand in top_candidates:
        if not isinstance(cand, dict):
            continue
        sym = cand.get("symbol") or cand.get("pair")
        if not sym:
            continue
        score = float(cand.get("opportunity_score") or cand.get("confidence") or 0)
        existing = cand_by_sym.get(sym)
        if not existing or score > float(existing.get("opportunity_score") or existing.get("confidence") or 0):
            cand_by_sym[sym] = cand
    unique_candidates = list(cand_by_sym.values())
    unique_candidates.sort(key=lambda item: float(item.get("opportunity_score") or item.get("confidence") or 0), reverse=True)
    summary["top_candidates"] = unique_candidates[:5]
    summary["realized_trade_pnl_idr"] = round(float(summary["realized_trade_pnl_idr"]), 2)
    return summary
