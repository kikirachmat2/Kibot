from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from Core.Support.ki_config import STATE_DIR


POLICY_FILE = Path("config/recovery_mode_policy.json")
OUTPUT_FILE = STATE_DIR / "recovery_mode_policy_state.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else default
    except Exception:
        return default
    return default


def build_recovery_mode_policy(bundle: Dict[str, Any] | None = None) -> Dict[str, Any]:
    bundle = bundle or {}
    policy = _read_json(POLICY_FILE, {})
    net_growth = bundle.get("net_growth_audit", {}) if isinstance(bundle.get("net_growth_audit"), dict) else {}
    daily_controls = bundle.get("daily_controls_audit", {}) if isinstance(bundle.get("daily_controls_audit"), dict) else {}
    fill_quality = bundle.get("fill_quality_audit", {}) if isinstance(bundle.get("fill_quality_audit"), dict) else {}
    closed_ok = int((bundle.get("round_trip_accounting", {}) or {}).get("stats", {}).get("closed_round_trips", 0) or 0) > 0
    daily_loss_breached = bool(bundle.get("capital_governor", {}).get("daily_loss_breached", False))
    profit_factor = float(net_growth.get("profit_factor") or 0.0) if net_growth else 0.0
    active = (
        str(net_growth.get("status") or "").upper() in {"FLAT_CHURN", "LOSING"}
        or daily_loss_breached
        or profit_factor < 1.0
    )
    payload = {
        "updated_at": bundle.get("updated_at") or "",
        "enabled": bool(policy.get("enabled", True)),
        "active": active,
        "reason": "daily loss lock and churn control active" if active else "recovery mode not needed",
        "daily_loss_breached": daily_loss_breached,
        "net_growth_status": str(net_growth.get("status") or ""),
        "profit_factor": profit_factor,
        "fill_quality": str(fill_quality.get("status") or ""),
        "closed_round_trip_accounting_ok": closed_ok,
        "policy": policy,
        "daily_controls": daily_controls,
    }
    OUTPUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload
