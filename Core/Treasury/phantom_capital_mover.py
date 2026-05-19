from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "phantom_capital_mover.json"


def write_phantom_capital_mover(payload: Dict[str, Any]) -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    resolved = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "NO_BRIDGE_NO_WITHDRAWAL",
        "total_phantom_value_idr": 0,
        "chain_balances": {"solana": {"sol_idr": 0, "tradable": True, "reason": ""}, "base": {"idrx_idr": 0, "tradable": True, "reason": ""}},
        "route_buckets": {"solana_jupiter": 0, "pumpfun_jupiter": 0, "pumpfun_native": 0, "base_swap": 0, "polymarket": 0, "future_web3": 0, "reserve": 0},
        "recommended_action": {"route": "", "action": "SCAN_NEXT", "amount_idr": 0, "reason": ""},
        "manual_transfer_required": {},
        "bridge": "ON",
        "withdrawal": "ON",
    }
    resolved.update(payload or {})
    STATE_FILE.write_text(json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")
    return resolved
