from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from Core.Support.ki_config import STATE_DIR


POLICY_FILE = Path("config/recovery_mode_policy.json")
OUTPUT_FILE = STATE_DIR / "churn_guard.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else default
    except Exception:
        return default
    return default


def evaluate_churn_guard(bundle: Dict[str, Any] | None = None) -> Dict[str, Any]:
    bundle = bundle or {}
    policy = _read_json(POLICY_FILE, {})
    net_growth = bundle.get("net_growth_audit", {}) if isinstance(bundle.get("net_growth_audit"), dict) else _read_json(STATE_DIR / "net_growth_audit.json", {})
    daily_controls = bundle.get("daily_controls_audit", {}) if isinstance(bundle.get("daily_controls_audit"), dict) else _read_json(STATE_DIR / "daily_controls_audit.json", {})
    recovery = bundle.get("recovery_mode_policy", {}) if isinstance(bundle.get("recovery_mode_policy"), dict) else _read_json(STATE_DIR / "recovery_mode_policy_state.json", {})
    status = str(net_growth.get("status") or "").upper()
    profit_factor = float(net_growth.get("profit_factor") or 0.0) if net_growth else 0.0
    daily_loss_breached = bool(bundle.get("capital_governor", {}).get("daily_loss_breached", False))
    flat_churn = status == "FLAT_CHURN"
    losing = status == "LOSING"
    active = bool(recovery.get("active")) or flat_churn or losing or daily_loss_breached or profit_factor < 1.0
    payload = {
        "updated_at": bundle.get("updated_at") or "",
        "enabled": bool(policy.get("enabled", True)),
        "active": active,
        "net_growth_status": status,
        "profit_factor": profit_factor,
        "daily_loss_breached": daily_loss_breached,
        "max_new_round_trips_next_day": 3 if flat_churn else None,
        "max_micro_probes_next_day": 1 if flat_churn else None,
        "require_tighter_spread_pct": 0.4 if flat_churn else float(policy.get("actions", {}).get("max_spread_pct", 1.0) or 1.0),
        "disable_scale_up": bool(policy.get("actions", {}).get("disable_scale_up", True)) or profit_factor < 1.0,
        "allow_micro_probe": bool(policy.get("actions", {}).get("allow_micro_probe", False)) and not daily_loss_breached,
        "allow_exit_management": True,
        "lock_new_entries": daily_loss_breached or losing,
        "reason": (
            "daily loss breach" if daily_loss_breached else
            ("flat churn" if flat_churn else ("losing" if losing else "profit factor below 1.0"))
        ),
        "daily_controls_recommendation": str(daily_controls.get("recommendation") or ""),
        "policy": policy,
    }
    OUTPUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload
