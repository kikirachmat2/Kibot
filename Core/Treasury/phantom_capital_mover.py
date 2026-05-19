from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "phantom_capital_mover.json"
TREASURY_FILE = STATE_DIR / "phantom_treasury.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def write_phantom_capital_mover(payload: Dict[str, Any]) -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    bridge_on = os.getenv("KIBOT_ENABLE_REAL_BRIDGE", "false").strip().lower() in {"1", "true", "yes", "on", "live", "production"}
    withdrawal_on = os.getenv("KIBOT_ENABLE_REAL_WITHDRAWAL", "false").strip().lower() in {"1", "true", "yes", "on", "live", "production"}
    treasury = _read_json(TREASURY_FILE, {})
    chains = treasury.get("chains", {}) if isinstance(treasury, dict) else {}
    balances = treasury.get("buckets", {}) if isinstance(treasury, dict) else {}
    sol_balance = float(treasury.get("sol_balance") or chains.get("solana", {}).get("sol_balance") or 0.0)
    base_idrx_balance = float(treasury.get("base_idrx_balance") or chains.get("base", {}).get("normalized_idrx") or 0.0)
    total_value_idr = float(treasury.get("total_value_idr") or 0.0)
    if not total_value_idr:
        total_value_idr = sol_balance * 170.0 * 16000.0 + base_idrx_balance

    min_sol_trade = float(os.getenv("WEB3_MIN_SOL_TRADE", "0.0005") or 0.0005)
    reserve_sol = float(os.getenv("WEB3_SOL_RESERVE", "0.003") or 0.003)
    tradable_sol = max(0.0, sol_balance - reserve_sol)
    if "recommended_action" in payload and isinstance(payload.get("recommended_action"), dict):
        recommended_action = dict(payload["recommended_action"])
    else:
        recommended_action = {}
    if not recommended_action:
        if bridge_on and withdrawal_on and sol_balance >= min_sol_trade:
            recommended_action = {
                "route": "solana_jupiter",
                "action": "ENTER",
                "amount_idr": int(balances.get("swap_idr", 0) or 0),
                "reason": "solana capital tradable via current-chain routing",
            }
        elif base_idrx_balance > 0:
            recommended_action = {
                "route": "base_swap",
                "action": "TRADE_ON_CURRENT_CHAIN",
                "amount_idr": int(base_idrx_balance),
                "reason": "base_idrx_available_but_no_direct_cross_chain_swap_route_to_solana",
            }
        else:
            recommended_action = {
                "route": "",
                "action": "SCAN_NEXT",
                "amount_idr": 0,
                "reason": "no_tradable_balance_or_no_route",
            }
    resolved = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "LIVE_BRIDGE_WITH_WITHDRAWAL" if bridge_on and withdrawal_on else "LIVE_TRADING",
        "total_phantom_value_idr": total_value_idr,
        "chain_balances": {
            "solana": {"sol_idr": int(sol_balance * 170.0 * 16000.0), "tradable": tradable_sol >= min_sol_trade, "reason": "" if tradable_sol >= min_sol_trade else "sol_balance_below_trade_min"},
            "base": {"idrx_idr": int(base_idrx_balance), "tradable": base_idrx_balance > 0, "reason": "" if base_idrx_balance > 0 else "base_idrx_zero"},
        },
        "route_buckets": {
            "solana_jupiter": int(balances.get("swap_idr", 0) or 0),
            "pumpfun_jupiter": int(balances.get("swap_idr", 0) or 0),
            "pumpfun_native": int(balances.get("swap_idr", 0) or 0),
            "base_swap": int(base_idrx_balance),
            "polymarket": int(balances.get("polymarket_idr", 0) or 0),
            "future_web3": int(balances.get("future_web3_idr", 0) or 0),
            "reserve": int(balances.get("reserve_idr", 0) or 0),
        },
        "recommended_action": recommended_action,
        "manual_transfer_required": {
            "required": bool(base_idrx_balance > 0 and tradable_sol < min_sol_trade and not bridge_on),
            "reason": "base_idrx_available_but_solana_route_needs_cross_chain_transfer" if base_idrx_balance > 0 and tradable_sol < min_sol_trade else "",
        },
        "bridge": "ON" if bridge_on else "OFF",
        "withdrawal": "ON" if withdrawal_on else "OFF",
    }
    resolved.update(payload or {})
    resolved["total_phantom_value_idr"] = float(resolved.get("total_phantom_value_idr") or total_value_idr)
    resolved["chain_balances"] = resolved.get("chain_balances") or {}
    resolved["route_buckets"] = resolved.get("route_buckets") or {}
    resolved["recommended_action"] = resolved.get("recommended_action") or recommended_action
    resolved["manual_transfer_required"] = resolved.get("manual_transfer_required") or {
        "required": bool(base_idrx_balance > 0 and tradable_sol < min_sol_trade and not bridge_on),
        "reason": "base_idrx_available_but_solana_route_needs_cross_chain_transfer" if base_idrx_balance > 0 and tradable_sol < min_sol_trade else "",
    }
    runtime = {
        "updated_at": resolved["updated_at"],
        "bridge_env": bridge_on,
        "withdrawal_env": withdrawal_on,
        "bridge_executor_ready": bool(resolved.get("bridge_executor_ready", bridge_on)),
        "withdrawal_executor_ready": bool(resolved.get("withdrawal_executor_ready", withdrawal_on)),
        "active_capital_paths": resolved.get("active_capital_paths", ["solana_jupiter", "pumpfun_jupiter", "base_swap", "polymarket", "future_web3"]) if (sol_balance >= min_sol_trade or base_idrx_balance > 0) else [],
        "blocked_capital_paths": resolved.get("blocked_capital_paths", {}),
        "next_capital_action": resolved.get("next_capital_action", resolved.get("recommended_action", {}).get("action", "SCAN_NEXT")),
        "reason": resolved.get("reason", resolved.get("recommended_action", {}).get("reason", "")),
    }
    STATE_FILE.write_text(json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")
    (STATE_DIR / "capital_movement_runtime.json").write_text(json.dumps(runtime, indent=2, ensure_ascii=False), encoding="utf-8")
    return resolved
