from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")


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
        return dt.astimezone(WIB)
    except Exception:
        return None


def _is_fresh(data: Dict[str, Any], *, max_age_s: int = 90) -> bool:
    updated = _parse_dt(data.get("updated_at"))
    if updated is None:
        return False
    age = datetime.now(WIB) - updated
    return age <= timedelta(seconds=max_age_s)


def _blocker_reason(blockers: Any) -> str:
    if not isinstance(blockers, list):
        return ""
    reasons: List[str] = []
    for item in blockers:
        if isinstance(item, dict):
            source = str(item.get("source") or "").strip()
            reason = str(item.get("reason") or "").strip()
            if source or reason:
                reasons.append(f"{source}:{reason}".strip(":"))
        elif item not in (None, "", False):
            reasons.append(str(item))
    return "; ".join(reasons)


def reconcile_risk_truth(
    live_truth: dict,
    capital_governor: dict,
    risk_state: dict,
    ai_patrol: dict,
    workflow: dict,
) -> dict:
    live_truth = live_truth if isinstance(live_truth, dict) else {}
    capital_governor = capital_governor if isinstance(capital_governor, dict) else {}
    risk_state = risk_state if isinstance(risk_state, dict) else {}
    ai_patrol = ai_patrol if isinstance(ai_patrol, dict) else {}
    workflow = workflow if isinstance(workflow, dict) else {}

    canonical_blockers: List[dict[str, Any]] = []
    advisory_warnings: List[dict[str, Any]] = []
    ignored_stale_blockers: List[dict[str, Any]] = []
    inconsistencies: List[str] = []

    live_updated = _parse_dt(live_truth.get("updated_at"))
    live_fresh = _is_fresh(live_truth, max_age_s=90)
    gov_updated = _parse_dt(capital_governor.get("updated_at") or capital_governor.get("timestamp"))
    gov_fresh = gov_updated is not None and (datetime.now(WIB) - gov_updated) <= timedelta(minutes=15)
    ai_updated = _parse_dt(ai_patrol.get("updated_at") or ai_patrol.get("timestamp"))
    ai_fresh = ai_updated is not None and (datetime.now(WIB) - ai_updated) <= timedelta(minutes=15)

    live_risk = str(live_truth.get("risk_state") or "UNKNOWN").upper()
    gov_status = str(capital_governor.get("status") or "UNKNOWN").upper()
    gov_allow = bool(capital_governor.get("allow_new_orders", False))
    gov_reason = str(capital_governor.get("allow_new_orders_reason") or "").strip()
    workflow_status = str(workflow.get("overall_status") or "").upper()

    daily_pnl = _safe_float(
        live_truth.get("net_pnl_today_idr"),
        _safe_float(capital_governor.get("daily_pnl_idr"), _safe_float(risk_state.get("daily_pnl"), 0.0)),
    )
    daily_anchor = _safe_float(
        capital_governor.get("start_total_equity_idr"),
        _safe_float(capital_governor.get("reset_total_balance_idr"), 0.0),
    )
    current_equity = _safe_float(
        live_truth.get("total_equity_idr"),
        _safe_float(capital_governor.get("current_total_equity_idr"), 0.0),
    )
    daily_pnl_pct = _safe_float(
        capital_governor.get("daily_pnl_pct"),
        _safe_float(capital_governor.get("daily_return_pct"), 0.0),
    )
    from Core.Support.ki_config import KiConfig

    dynamic_loss_cap_idr = daily_anchor * (KiConfig.MAX_DAILY_LOSS_PERCENT / 100.0) if daily_anchor > 0 else 0.0
    threshold = _safe_float(
        dynamic_loss_cap_idr,
        _safe_float(
            capital_governor.get("max_daily_loss_idr"),
            _safe_float(capital_governor.get("daily_loss_cap_idr"), 0.0),
        )
    )

    canonical_state = "OK"
    allow_new_orders = True
    reason_bits: List[str] = []
    loss_cap_corroborated = False

    if not live_fresh:
        canonical_state = "LOCKED"
        allow_new_orders = False
        reason_bits.append("live_truth_stale")
        canonical_blockers.append({"source": "live_truth", "reason": "stale"})
    if live_risk in {"EMERGENCY", "LOCKED"}:
        canonical_state = "EMERGENCY" if live_risk == "EMERGENCY" else "LOCKED"
        allow_new_orders = False
        canonical_blockers.append({"source": "live_truth", "reason": f"risk_state={live_risk}"})
    if gov_status in {"BLOCKED_WITH_REASON", "LOCKED", "ERROR"} or not gov_allow:
        gov_reason_l = gov_reason.lower()
        loss_cap_claimed = "global_daily_loss_cap_breached" in gov_reason_l or "global_hard_stop" in gov_reason_l
        loss_cap_corroborated = loss_cap_claimed and daily_pnl < 0 and threshold > 0 and abs(daily_pnl) >= threshold
        if gov_fresh and (not loss_cap_claimed or loss_cap_corroborated):
            canonical_state = "LOCKED"
            allow_new_orders = False
            canonical_blockers.append({"source": "capital_governor", "reason": gov_reason or gov_status or "orders_disabled"})
        else:
            advisory_warnings.append(
                {
                    "source": "capital_governor",
                    "reason": gov_reason or gov_status or "stale_or_unverified",
                    "evidence": {
                        "fresh": gov_fresh,
                        "loss_cap_claimed": loss_cap_claimed,
                        "loss_cap_corroborated": loss_cap_corroborated,
                    },
                }
            )
            ignored_stale_blockers.append(
                {"source": "capital_governor", "reason": gov_reason or gov_status or "stale_or_unverified"}
            )
            allow_new_orders = True

    if daily_pnl < 0 and threshold > 0 and abs(daily_pnl) >= threshold:
        if gov_fresh or live_risk in {"LOCKED", "EMERGENCY"}:
            canonical_state = "LOCKED"
            allow_new_orders = False
            canonical_blockers.append(
                {
                    "source": "capital_governor",
                    "reason": f"global_daily_loss_cap_breached (Rp {daily_pnl:.2f} <= -Rp {threshold:.2f} [{KiConfig.MAX_DAILY_LOSS_PERCENT}% cap])",
                    "evidence": {
                        "source_equity": current_equity,
                        "daily_anchor": daily_anchor,
                        "current_equity": current_equity,
                        "daily_pnl": daily_pnl,
                        "daily_pnl_pct": daily_pnl_pct,
                        "threshold": threshold,
                        "calculated_at": datetime.now(WIB).isoformat(),
                        "source_files": ["state/live_truth.json", "state/capital_governor.json", "state/risk_state.json"],
                    },
                }
            )
        else:
            advisory_warnings.append(
                {
                    "source": "ai_patrol",
                    "reason": f"stale global_daily_loss_cap_breached ignored ({daily_pnl:.2f} vs -{threshold:.2f})",
                    "evidence": {
                        "source_equity": current_equity,
                        "daily_anchor": daily_anchor,
                        "current_equity": current_equity,
                        "daily_pnl": daily_pnl,
                        "daily_pnl_pct": daily_pnl_pct,
                        "threshold": threshold,
                        "calculated_at": datetime.now(WIB).isoformat(),
                        "source_files": ["state/ai_patrol.json"],
                    },
                }
            )
            ignored_stale_blockers.append(
                {"source": "ai_patrol", "reason": "global_daily_loss_cap_breached"}
            )

    raw_ai_alerts = ai_patrol.get("alerts")
    ai_alerts: list = list(raw_ai_alerts) if isinstance(raw_ai_alerts, list) else []
    ai_runtime = ai_patrol.get("runtime_semantics") if isinstance(ai_patrol.get("runtime_semantics"), dict) else {}
    for alert in ai_alerts:
        text = str(alert or "")
        if "global_daily_loss_cap_breached" in text:
            if daily_pnl >= 0 or (ai_updated is not None and (datetime.now(WIB) - ai_updated) > timedelta(minutes=15)):
                ignored_stale_blockers.append({"source": "ai_patrol", "reason": text})
                advisory_warnings.append({"source": "ai_patrol", "reason": "stale loss cap blocker ignored", "evidence": {"alert": text}})
            elif not gov_fresh and live_fresh:
                ignored_stale_blockers.append({"source": "ai_patrol", "reason": text})
                advisory_warnings.append({"source": "ai_patrol", "reason": "loss cap blocker not corroborated by governor", "evidence": {"alert": text}})
            elif canonical_state != "LOCKED":
                canonical_blockers.append({"source": "ai_patrol", "reason": text})
        elif "orders_blocked" in text or "dispatcher_blocked" in text:
            advisory_warnings.append({"source": "ai_patrol", "reason": text, "evidence": {}})

    if not ai_fresh and ai_alerts:
        advisory_warnings.append({"source": "ai_patrol", "reason": "stale ai_patrol ignored", "evidence": {"age_ok": False}})

    if not allow_new_orders and canonical_state == "OK":
        canonical_state = "CAUTION"

    if live_fresh and gov_fresh and live_risk == "OK" and gov_status not in {"BLOCKED_WITH_REASON", "LOCKED", "ERROR"} and not canonical_blockers:
        canonical_state = "OK"
        allow_new_orders = True
    if not canonical_blockers and not allow_new_orders and canonical_state == "OK":
        canonical_state = "CAUTION"

    if "global_daily_loss_cap_breached" in gov_reason.lower() or "global_hard_stop" in gov_reason.lower():
        if not any(item.get("source") == "capital_governor" for item in canonical_blockers) and loss_cap_corroborated:
            canonical_blockers.append({"source": "capital_governor", "reason": gov_reason})
            allow_new_orders = False
            canonical_state = "LOCKED"

    if not live_fresh:
        canonical_state = "LOCKED"
        allow_new_orders = False

    if workflow_status.startswith("INFRA_BLOCKED"):
        canonical_state = "LOCKED"
        allow_new_orders = False
        canonical_blockers.append({"source": "workflow", "reason": workflow_status})

    reason = ""
    if canonical_blockers:
        reason = _blocker_reason(canonical_blockers)
    elif advisory_warnings:
        reason = "; ".join(str(item.get("reason") or "") for item in advisory_warnings if isinstance(item, dict) and item.get("reason"))
    else:
        reason = "live_truth and capital_governor are OK"

    return {
        "canonical_risk_state": canonical_state,
        "allow_new_orders": allow_new_orders,
        "canonical_blockers": canonical_blockers,
        "advisory_warnings": advisory_warnings,
        "ignored_stale_blockers": ignored_stale_blockers,
        "inconsistencies": inconsistencies,
        "reason": reason,
        "meta": {
            "live_truth_fresh": live_fresh,
            "capital_governor_fresh": gov_fresh,
            "ai_patrol_fresh": ai_fresh,
            "daily_pnl": daily_pnl,
            "threshold": threshold,
            "daily_anchor": daily_anchor,
            "current_equity": current_equity,
        },
    }
