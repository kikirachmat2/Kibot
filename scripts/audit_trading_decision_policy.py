#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Support.ki_config import STATE_DIR
from Core.Support.recovery_reset_plan import build_recovery_reset_plan
from Core.Support.churn_guard import evaluate_churn_guard
from Core.Support.growth_audit import audit_daily_controls, audit_fill_quality, audit_net_growth
from Core.Support.money_movement_audit import load_state_bundle

OUT_FILE = STATE_DIR / "trading_decision_policy_audit.json"


def build_trading_decision_policy_audit() -> Dict[str, Any]:
    bundle = load_state_bundle()
    recovery = build_recovery_reset_plan(bundle)
    churn = evaluate_churn_guard(bundle)
    net_growth = audit_net_growth(bundle)
    fill_quality = audit_fill_quality(bundle)
    daily_controls = audit_daily_controls(bundle)
    capital = bundle.get("capital_governor", {}) if isinstance(bundle.get("capital_governor"), dict) else {}
    strategy_actions = _read_json(STATE_DIR / "strategy_control_actions.json", {})
    no_trade = bundle.get("no_trade_forensics", {}) if isinstance(bundle.get("no_trade_forensics"), dict) else {}

    max_daily_loss = float(capital.get("max_daily_loss_idr") or 0.0)
    allow_new_orders = bool(capital.get("allow_new_orders", False))
    rec_mode = recovery.get("after_reset_mode")
    recommendation = "TIGHTEN"
    if fill_quality.get("status") == "ACCOUNTING_OK" and net_growth.get("status") == "PROFITABLE" and allow_new_orders:
        recommendation = "KEEP"
    elif net_growth.get("status") in {"FLAT_CHURN", "LOSING"} or fill_quality.get("status") != "ACCOUNTING_OK":
        recommendation = "TIGHTEN"

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": recommendation,
        "allow_new_orders": allow_new_orders,
        "max_daily_loss_idr": max_daily_loss,
        "recovery_mode": rec_mode,
        "net_growth": net_growth,
        "fill_quality": fill_quality,
        "daily_controls": daily_controls,
        "churn_guard": churn,
        "strategy_control_actions": strategy_actions,
        "no_trade_forensics": no_trade,
        "decision": {
            "daily_loss_lock": bool(capital.get("daily_loss_breached") or "global_daily_loss_cap_breached" in str(capital.get("allow_new_orders_reason") or "").lower()),
            "no_micro_probe": not bool((recovery.get("policy") or {}).get("allow_micro_probe", False)),
            "no_scale_up": not bool((recovery.get("policy") or {}).get("allow_scale_up", False)),
            "allow_exit_management": bool((recovery.get("policy") or {}).get("allow_exit_management", True)),
        },
        "reason": "policy tightened due to churn or accounting constraints" if recommendation == "TIGHTEN" else "policy stable",
    }
    OUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, (dict, list)) else default
    except Exception:
        return default
    return default


def main() -> int:
    payload = build_trading_decision_policy_audit()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"OK:TRADING_DECISION_POLICY_AUDITED status={payload.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
