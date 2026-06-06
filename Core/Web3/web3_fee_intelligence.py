from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
FEE_STATE_FILE = STATE_DIR / "web3_fee_state.json"

SOLANA_BASE_FEE_LAMPORTS = 5000
SOLANA_PRIORITY_FEE_CAP_LAMPORTS = 1_000_000
JUPITER_GASLESS_CAP_PCT = 0.10
BASE_MIN_GAS_PCT_NOTE = 0.80


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return float(default)
    try:
        return float(str(raw).strip() or default)
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    try:
        return int(float(str(raw).strip() or default))
    except Exception:
        return int(default)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "enabled", "live"}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _read_nested(snapshot: Dict[str, Any] | None, paths: Iterable[str], default: float = 0.0) -> float:
    if not isinstance(snapshot, dict):
        return float(default)
    for path in paths:
        node: Any = snapshot
        ok = True
        for bit in str(path).split("."):
            if not isinstance(node, dict) or bit not in node:
                ok = False
                break
            node = node.get(bit)
        if ok:
            try:
                return float(node)
            except Exception:
                continue
    return float(default)


def _sol_idr_rate() -> float:
    usd_idr = _env_float("USD_IDR_RATE", 16000.0)
    sol_usd = _env_float("SOL_USD_RATE", 170.0)
    return usd_idr * sol_usd


def _base_fee_defaults() -> Dict[str, float]:
    base_total = _env_float("BASE_GAS_IDR_ESTIMATE", 15000.0)
    l2 = _env_float("BASE_L2_EXECUTION_GAS_IDR_ESTIMATE", base_total * 0.40)
    l1 = _env_float("BASE_L1_SECURITY_GAS_IDR_ESTIMATE", max(base_total - l2, base_total * 0.60))
    priority = _env_float("BASE_PRIORITY_FEE_IDR_ESTIMATE", 0.0)
    total = max(0.0, l2 + l1 + priority)
    return {"l2": l2, "l1": l1, "priority": priority, "total": total}


def _solana_fee_model(
    *,
    route: str,
    trade_size_idr: float,
    balance_snapshot: Dict[str, Any] | None,
    quote: Dict[str, Any] | None,
    route_context: Dict[str, Any] | None,
) -> Dict[str, Any]:
    signatures = max(1, _env_int("SOLANA_SIGNATURE_COUNT_ESTIMATE", 1))
    priority_lamports = _safe_float(
        (quote or {}).get("priority_fee_lamports"),
        _env_float("SOLANA_PRIORITY_FEE_LAMPORTS_ESTIMATE", 0.0),
    )
    priority_lamports = max(0.0, min(priority_lamports, float(SOLANA_PRIORITY_FEE_CAP_LAMPORTS)))
    base_lamports = float(SOLANA_BASE_FEE_LAMPORTS * signatures)
    total_lamports = base_lamports + priority_lamports
    sol_rate = _sol_idr_rate()
    fee_idr = total_lamports / 1_000_000_000.0 * sol_rate
    gas_balance_sol = _read_nested(
        balance_snapshot,
        (
            "sol_balance",
            "chains.solana.sol_balance",
            "available_balances.sol_balance",
            "available_balances.solana_sol_balance",
        ),
    )
    reserve_sol = _env_float("WEB3_SOL_RESERVE", _env_float("SOLANA_GAS_RESERVE_SOL", 0.003))
    has_native_gas = gas_balance_sol > reserve_sol
    gasless_supported = trade_size_idr > 0 and fee_idr <= trade_size_idr * JUPITER_GASLESS_CAP_PCT
    gas_mode = "paid" if has_native_gas else ("gasless" if gasless_supported else "blocked")
    gas_affordable = has_native_gas or gasless_supported
    gas_reason = "solana_network_fee_plus_priority_fee"
    if not has_native_gas:
        if gasless_supported:
            gas_reason = "gasless_fallback_under_10pct_cap"
        else:
            gas_reason = "gasless_surcharge_exceeds_10pct_cap" if trade_size_idr > 0 else "solana_gas_balance_below_reserve"
    if has_native_gas and priority_lamports > 0:
        gas_reason = "solana_network_fee_plus_priority_fee"

    gasless_cap_idr = trade_size_idr * JUPITER_GASLESS_CAP_PCT if trade_size_idr > 0 else 0.0
    if trade_size_idr > 0:
        min_profitable_trade_idr = max(fee_idr * 1.15, fee_idr / JUPITER_GASLESS_CAP_PCT)
        fee_ratio_pct = (fee_idr / trade_size_idr) * 100.0
    else:
        min_profitable_trade_idr = fee_idr * 10.0
        fee_ratio_pct = 0.0

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "route": route,
        "route_family": "solana",
        "gas_mode": gas_mode,
        "gas_affordable": gas_affordable,
        "gas_reason": gas_reason,
        "gas_fee_idr": round(fee_idr, 2),
        "gas_floor_idr": round(fee_idr, 2),
        "gasless_cap_idr": round(gasless_cap_idr, 2),
        "fee_ratio_pct": round(fee_ratio_pct, 4),
        "trade_size_idr": round(trade_size_idr, 2),
        "min_profitable_trade_idr": round(min_profitable_trade_idr, 2),
        "charged_on_failure": True,
        "balance_snapshot": {
            "sol_balance": round(gas_balance_sol, 8),
            "reserve_sol": round(reserve_sol, 8),
            "has_native_gas": has_native_gas,
        },
        "fee_breakdown": {
            "base_fee_lamports": base_lamports,
            "priority_fee_lamports": priority_lamports,
            "total_fee_lamports": total_lamports,
            "sol_idr_rate": sol_rate,
            "network_fee_idr": round(fee_idr, 2),
            "gasless_cap_pct": JUPITER_GASLESS_CAP_PCT,
        },
        "documentation_basis": [
            "solana_base_fee_5000_lamports_per_signature",
            "solana_priority_fee_optional_and_charged_even_if_tx_fails",
            "jupiter_gasless_last_resort_up_to_10pct_cap",
        ],
    }


def _base_fee_model(
    *,
    route: str,
    trade_size_idr: float,
    balance_snapshot: Dict[str, Any] | None,
    quote: Dict[str, Any] | None,
    route_context: Dict[str, Any] | None,
) -> Dict[str, Any]:
    defaults = _base_fee_defaults()
    base_balance_idr = _read_nested(
        balance_snapshot,
        (
            "base_gas_balance_idr",
            "eth_balance_idr",
            "base_eth_balance_idr",
            "chains.base.eth_balance_idr",
            "chains.base.gas_balance_idr",
        ),
    )
    if base_balance_idr <= 0:
        base_balance_idr = _read_nested(balance_snapshot, ("buckets.reserve_idr",), 0.0)
    l1_ratio = defaults["l1"] / max(defaults["total"], 1.0)
    gas_affordable = True
    gas_reason = "base_l2_execution_plus_l1_security_fee"
    if base_balance_idr > 0 and base_balance_idr < defaults["total"]:
        gas_affordable = False
        gas_reason = "base_gas_balance_below_fee_floor"
    elif trade_size_idr > 0 and l1_ratio >= BASE_MIN_GAS_PCT_NOTE and trade_size_idr < defaults["total"] * 20.0:
        gas_affordable = False
        gas_reason = "base_l1_fee_dominates_small_trade"

    fee_ratio_pct = (defaults["total"] / trade_size_idr) * 100.0 if trade_size_idr > 0 else 0.0
    min_profitable_trade_idr = max(defaults["total"] * 1.25, defaults["total"] / 0.10 if trade_size_idr > 0 else defaults["total"] * 10.0)

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "route": route,
        "route_family": "base",
        "gas_mode": "paid" if gas_affordable else "blocked",
        "gas_affordable": gas_affordable,
        "gas_reason": gas_reason,
        "gas_fee_idr": round(defaults["total"], 2),
        "gas_floor_idr": round(defaults["total"], 2),
        "gasless_cap_idr": 0.0,
        "fee_ratio_pct": round(fee_ratio_pct, 4),
        "trade_size_idr": round(trade_size_idr, 2),
        "min_profitable_trade_idr": round(min_profitable_trade_idr, 2),
        "charged_on_failure": True,
        "balance_snapshot": {
            "base_gas_balance_idr": round(base_balance_idr, 2),
            "l1_ratio": round(l1_ratio, 4),
        },
        "fee_breakdown": {
            "l2_execution_idr": round(defaults["l2"], 2),
            "l1_security_idr": round(defaults["l1"], 2),
            "priority_fee_idr": round(defaults["priority"], 2),
            "total_fee_idr": round(defaults["total"], 2),
            "base_fee_policy": "l2_execution_plus_l1_security",
        },
        "documentation_basis": [
            "base_l2_execution_fee_plus_l1_security_fee",
            "base_l1_fee_can_dominate_small_trades",
            "base_l1_fee_upper_bound_is_available_before_signing",
        ],
    }


def _bridge_fee_model(
    *,
    route: str,
    trade_size_idr: float,
    balance_snapshot: Dict[str, Any] | None,
    quote: Dict[str, Any] | None,
    route_context: Dict[str, Any] | None,
    fee_hint_idr: float = 0.0,
) -> Dict[str, Any]:
    route_context = route_context or {}
    from_chain = str(route_context.get("from_chain") or route_context.get("source_chain") or "").lower()
    to_chain = str(route_context.get("to_chain") or route_context.get("destination_chain") or "").lower()
    source_model: Dict[str, Any] = {}
    destination_model: Dict[str, Any] = {}

    if from_chain in {"solana", "pumpfun"}:
        source_model = _solana_fee_model(route=from_chain, trade_size_idr=trade_size_idr, balance_snapshot=balance_snapshot, quote=quote, route_context=route_context)
    elif from_chain in {"base"}:
        source_model = _base_fee_model(route=from_chain, trade_size_idr=trade_size_idr, balance_snapshot=balance_snapshot, quote=quote, route_context=route_context)

    if to_chain in {"solana", "pumpfun"}:
        destination_model = _solana_fee_model(route=to_chain, trade_size_idr=trade_size_idr, balance_snapshot=balance_snapshot, quote=quote, route_context=route_context)
    elif to_chain in {"base"}:
        destination_model = _base_fee_model(route=to_chain, trade_size_idr=trade_size_idr, balance_snapshot=balance_snapshot, quote=quote, route_context=route_context)

    bridge_fee = max(0.0, float(fee_hint_idr or 0.0))
    total_fee_idr = bridge_fee + float(source_model.get("gas_fee_idr", 0.0)) + float(destination_model.get("gas_fee_idr", 0.0))
    gas_reason = "bridge_fee_plus_chain_fees"
    gas_affordable = True
    if trade_size_idr > 0 and total_fee_idr > trade_size_idr:
        gas_affordable = False
        gas_reason = "bridge_fee_exceeds_trade_size"

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "route": route,
        "route_family": "bridge",
        "gas_mode": "paid" if gas_affordable else "blocked",
        "gas_affordable": gas_affordable,
        "gas_reason": gas_reason,
        "gas_fee_idr": round(total_fee_idr, 2),
        "gas_floor_idr": round(total_fee_idr, 2),
        "gasless_cap_idr": 0.0,
        "fee_ratio_pct": round((total_fee_idr / trade_size_idr) * 100.0, 4) if trade_size_idr > 0 else 0.0,
        "trade_size_idr": round(trade_size_idr, 2),
        "min_profitable_trade_idr": round(total_fee_idr * 1.25, 2),
        "charged_on_failure": True,
        "balance_snapshot": {
            "from_chain": from_chain,
            "to_chain": to_chain,
        },
        "fee_breakdown": {
            "bridge_fee_idr": round(bridge_fee, 2),
            "source_chain_fee_idr": round(float(source_model.get("gas_fee_idr", 0.0)), 2),
            "destination_chain_fee_idr": round(float(destination_model.get("gas_fee_idr", 0.0)), 2),
            "total_fee_idr": round(total_fee_idr, 2),
        },
        "documentation_basis": [
            "cross_chain_routes_need_source_and_destination_fee_budget",
            "bridge_fee_is_non_refundable_once_committed",
        ],
    }


def build_fee_intelligence(
    route: str,
    *,
    trade_size_idr: float = 0.0,
    balance_snapshot: Dict[str, Any] | None = None,
    quote: Dict[str, Any] | None = None,
    route_context: Dict[str, Any] | None = None,
    fee_hint_idr: float = 0.0,
) -> Dict[str, Any]:
    route = str(route or "").strip().lower()
    route_context = route_context or {}

    if route in {"solana", "solana_jupiter", "solana_meme", "pumpfun_jupiter", "pumpfun_native"}:
        payload = _solana_fee_model(
            route=route,
            trade_size_idr=trade_size_idr,
            balance_snapshot=balance_snapshot,
            quote=quote,
            route_context=route_context,
        )
    elif route in {"base", "base_swap"}:
        payload = _base_fee_model(
            route=route,
            trade_size_idr=trade_size_idr,
            balance_snapshot=balance_snapshot,
            quote=quote,
            route_context=route_context,
        )
    elif route in {"bridge", "cross_chain", "withdrawal", "bridge_router"} or route_context.get("from_chain") or route_context.get("to_chain"):
        payload = _bridge_fee_model(
            route=route or "bridge",
            trade_size_idr=trade_size_idr,
            balance_snapshot=balance_snapshot,
            quote=quote,
            route_context=route_context,
            fee_hint_idr=fee_hint_idr,
        )
    else:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "route": route,
            "route_family": "unknown",
            "gas_mode": "unknown",
            "gas_affordable": True,
            "gas_reason": "route_not_fee_profiled",
            "gas_fee_idr": 0.0,
            "gas_floor_idr": 0.0,
            "gasless_cap_idr": 0.0,
            "fee_ratio_pct": 0.0,
            "trade_size_idr": round(trade_size_idr, 2),
            "min_profitable_trade_idr": 0.0,
            "charged_on_failure": False,
            "balance_snapshot": {},
            "fee_breakdown": {},
            "documentation_basis": [
                "unknown_route_family_no_fee_profile",
            ],
        }

    payload["route_context"] = {
        "source_chain": route_context.get("source_chain", ""),
        "destination_chain": route_context.get("destination_chain", ""),
        "from_chain": route_context.get("from_chain", ""),
        "to_chain": route_context.get("to_chain", ""),
        "source": route_context.get("source", ""),
    }
    write_fee_state(payload)
    return payload


def write_fee_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    resolved = dict(payload or {})
    resolved["updated_at"] = resolved.get("updated_at") or datetime.now(timezone.utc).isoformat()
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        FEE_STATE_FILE.write_text(json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")
    except PermissionError:
        # Web3 is retired in Indodax-only runtime, and production state files may
        # be owned by systemd. Fee intelligence should still return a safe
        # payload instead of crashing a caller that is only asking for a reject.
        resolved["state_write_skipped"] = "permission_denied"
    return resolved
