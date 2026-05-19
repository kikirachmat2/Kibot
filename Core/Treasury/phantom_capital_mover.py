from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "phantom_capital_mover.json"


def write_phantom_capital_mover(payload: Dict[str, Any]) -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    bridge_on = os.getenv("KIBOT_ENABLE_REAL_BRIDGE", "false").strip().lower() in {"1", "true", "yes", "on", "live", "production"}
    withdrawal_on = os.getenv("KIBOT_ENABLE_REAL_WITHDRAWAL", "false").strip().lower() in {"1", "true", "yes", "on", "live", "production"}
    resolved = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "LIVE_BRIDGE_WITH_WITHDRAWAL" if bridge_on and withdrawal_on else "LIVE_TRADING",
        "total_phantom_value_idr": 0,
        "chain_balances": {"solana": {"sol_idr": 0, "tradable": True, "reason": ""}, "base": {"idrx_idr": 0, "tradable": True, "reason": ""}},
        "route_buckets": {"solana_jupiter": 0, "pumpfun_jupiter": 0, "pumpfun_native": 0, "base_swap": 0, "polymarket": 0, "future_web3": 0, "reserve": 0},
        "recommended_action": {"route": "", "action": "SCAN_NEXT", "amount_idr": 0, "reason": ""},
        "manual_transfer_required": {},
        "bridge": "ON" if bridge_on else "OFF",
        "withdrawal": "ON" if withdrawal_on else "OFF",
    }
    resolved.update(payload or {})
    runtime = {
        "updated_at": resolved["updated_at"],
        "bridge_env": bridge_on,
        "withdrawal_env": withdrawal_on,
        "bridge_executor_ready": bool(resolved.get("bridge_executor_ready", bridge_on)),
        "withdrawal_executor_ready": bool(resolved.get("withdrawal_executor_ready", withdrawal_on)),
        "active_capital_paths": resolved.get("active_capital_paths", ["solana_jupiter", "pumpfun_jupiter", "base_swap", "polymarket", "future_web3"]),
        "blocked_capital_paths": resolved.get("blocked_capital_paths", {}),
        "next_capital_action": resolved.get("next_capital_action", resolved.get("recommended_action", {}).get("action", "SCAN_NEXT")),
        "reason": resolved.get("reason", resolved.get("recommended_action", {}).get("reason", "")),
    }
    STATE_FILE.write_text(json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")
    (STATE_DIR / "capital_movement_runtime.json").write_text(json.dumps(runtime, indent=2, ensure_ascii=False), encoding="utf-8")
    return resolved
