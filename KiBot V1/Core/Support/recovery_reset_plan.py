from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict
from zoneinfo import ZoneInfo

from Core.Support.ki_config import STATE_DIR


RESET_FILE = STATE_DIR / "recovery_reset_plan.json"
POLICY_FILE = Path("config/recovery_mode_policy.json")
WIB = ZoneInfo("Asia/Jakarta")


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else default
    except Exception:
        return default
    return default


def _parse_hour(raw: Any, default: int = 0) -> int:
    try:
        hour = int(float(raw))
    except Exception:
        hour = default
    return max(0, min(23, hour))


def _next_reset_dt(now: datetime, reset_hour: int) -> datetime:
    candidate = now.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    return candidate


def build_recovery_reset_plan(bundle: Dict[str, Any] | None = None) -> Dict[str, Any]:
    bundle = bundle or {}
    policy = _read_json(POLICY_FILE, {})
    governor = bundle.get("capital_governor", {}) if isinstance(bundle.get("capital_governor"), dict) else _read_json(STATE_DIR / "capital_governor.json", {})
    net_growth = bundle.get("net_growth_audit", {}) if isinstance(bundle.get("net_growth_audit"), dict) else _read_json(STATE_DIR / "net_growth_audit.json", {})
    fill_quality = bundle.get("fill_quality_audit", {}) if isinstance(bundle.get("fill_quality_audit"), dict) else _read_json(STATE_DIR / "fill_quality_audit.json", {})
    now = datetime.now(WIB)
    reset_hour = _parse_hour(os.getenv("KIBOT_DAILY_RESET_HOUR", "0"), 0)
    next_reset = _next_reset_dt(now, reset_hour)
    threshold = int(bundle.get("max_round_trips", 3) or 3)
    micro = int(bundle.get("max_micro_probes", 1) or 1)
    active = bool(governor.get("daily_loss_breached", False)) or str(net_growth.get("status") or "").upper() in {"FLAT_CHURN", "LOSING"}
    payload = {
        "updated_at": now.isoformat(),
        "current_state": "LOCKED_DAILY_LOSS" if active else "CONSERVATIVE_RECOVERY",
        "next_reset_at": next_reset.isoformat(),
        "timezone": "Asia/Jakarta",
        "current_day": now.strftime("%Y-%m-%d"),
        "reset_hour": reset_hour,
        "seconds_until_reset": max(0, int((next_reset - now).total_seconds())),
        "after_reset_mode": "CONSERVATIVE_RECOVERY",
        "max_round_trips": int(bundle.get("max_round_trips", threshold) or threshold),
        "max_micro_probes": int(bundle.get("max_micro_probes", micro) or micro),
        "scale_up": False,
        "allow_scale_up": False,
        "allow_micro_probe": False,
        "daily_loss_breached": bool(governor.get("daily_loss_breached", False)),
        "fill_quality_status": str(fill_quality.get("status") or ""),
        "net_growth_status": str(net_growth.get("status") or ""),
        "policy": policy,
        "allowed_actions": ["scan", "forensics", "exit_management", "safe_micro_probe_after_reset"],
        "blocked_actions": ["scale_up", "unknown_source_scale_up", "negative_edge_pairs", "manual_force_buy"],
    }
    RESET_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESET_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload
