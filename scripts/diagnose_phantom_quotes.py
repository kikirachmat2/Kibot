#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from Core.Support.ki_config import STATE_DIR


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else default
    except Exception:
        return default
    return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", False):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _route_for_target(target: Dict[str, Any]) -> str:
    route = str(target.get("route") or target.get("route_type") or target.get("sector") or target.get("chain") or "").lower()
    if route in {"jupiter_routable", "solana_jupiter"}:
        return "solana_jupiter"
    if route in {"pumpfun_bonding_curve", "pumpfun_native"}:
        return "pumpfun_native"
    if route in {"pumpfun_migrated", "pumpfun_jupiter"}:
        return "pumpfun_jupiter"
    if route in {"solana_meme"}:
        return "solana_meme"
    if route in {"base", "base_swap"}:
        return "base_swap"
    if route in {"polymarket"}:
        return "polymarket"
    if str(target.get("chain") or "").lower() == "base":
        return "base_swap"
    if str(target.get("sector") or "").lower() == "polymarket":
        return "polymarket"
    if str(target.get("chain") or "").lower() == "solana":
        return "solana_jupiter"
    return "future_web3"


def main() -> None:
    phantom = _read_json(STATE_DIR / "phantom_top_targets.json", {})
    treasury = _read_json(STATE_DIR / "phantom_treasury.json", {})
    rpc_health = _read_json(STATE_DIR / "phantom_rpc_health.json", {})
    quote_state = _read_json(STATE_DIR / "web3_quote_state.json", {})
    wallet = _read_json(STATE_DIR / "phantom_wallet.json", {})

    targets = phantom.get("top_targets", []) if isinstance(phantom, dict) else []
    failures: List[Dict[str, Any]] = []
    quote_ok_count = 0
    quote_fail_count = 0
    route_not_found = False
    size_too_small = False
    slippage_too_high = False
    price_impact_too_high = False
    rpc_degraded = False
    wallet_not_ready = False

    for item in targets if isinstance(targets, list) else []:
        if not isinstance(item, dict):
            continue
        route = _route_for_target(item)
        quote_ok = bool(item.get("quote_ok", False))
        reason = str(item.get("reason") or item.get("gas_reason") or "")
        slippage_bps = int(_as_float(item.get("slippage_bps") or item.get("max_slippage_bps") or 100, 100))
        price_impact_pct = _as_float(item.get("price_impact_pct") or item.get("slippage_pct") or 0.0, 0.0)
        amount = _as_float(item.get("amount_idr") or item.get("size_idr") or item.get("volume_or_liquidity") or 0.0, 0.0)
        min_size = float(quote_state.get("min_profitable_trade_idr") or item.get("min_profitable_trade_idr") or 10000.0)

        if quote_ok:
            quote_ok_count += 1
            continue

        quote_fail_count += 1
        failure_reason = "QUOTES_NOT_OK"
        if not route or route == "future_web3":
            failure_reason = "ROUTE_NOT_FOUND"
            route_not_found = True
        elif amount > 0 and amount < min_size:
            failure_reason = "SIZE_TOO_SMALL"
            size_too_small = True
        elif price_impact_pct and price_impact_pct > float(item.get("max_price_impact_pct") or 1.0):
            failure_reason = "PRICE_IMPACT_TOO_HIGH"
            price_impact_too_high = True
        elif slippage_bps > int(item.get("max_slippage_bps") or 100):
            failure_reason = "SLIPPAGE_TOO_HIGH"
            slippage_too_high = True
        elif str(rpc_health.get("status") or "").upper() not in {"OK", "HEALTHY", "RECONCILED"}:
            failure_reason = "RPC_DEGRADED"
            rpc_degraded = True
        elif not bool(wallet.get("pubkey") or wallet.get("public_key") or wallet.get("owner")) and item.get("route") in {"solana_jupiter", "pumpfun_jupiter", "pumpfun_native", "solana_meme", "base_swap"}:
            failure_reason = "WALLET_NOT_READY"
            wallet_not_ready = True

        failures.append(
            {
                "symbol": str(item.get("symbol") or item.get("asset") or item.get("market") or "").upper(),
                "reason": failure_reason,
                "jupiter_error": reason,
                "amount": amount,
                "slippage_bps": slippage_bps,
                "price_impact_pct": price_impact_pct if price_impact_pct else None,
            }
        )

    if quote_ok_count > 0 and quote_fail_count == 0:
        status = "QUOTE_OK"
    elif route_not_found:
        status = "ROUTE_NOT_FOUND"
    elif size_too_small:
        status = "SIZE_TOO_SMALL"
    elif slippage_too_high:
        status = "SLIPPAGE_TOO_HIGH"
    elif price_impact_too_high:
        status = "PRICE_IMPACT_TOO_HIGH"
    elif rpc_degraded:
        status = "RPC_DEGRADED"
    elif wallet_not_ready:
        status = "WALLET_NOT_READY"
    elif quote_fail_count > 0:
        status = "QUOTES_NOT_OK"
    else:
        status = "QUOTES_NOT_OK"

    diagnosis = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "targets_checked": len(targets) if isinstance(targets, list) else 0,
        "quote_ok_count": quote_ok_count,
        "quote_fail_count": quote_fail_count,
        "failures": failures,
        "recommended_fix": (
            "increase minimum viable probe size or reject clearly"
            if size_too_small else
            "filter route/mint mapping and confirm token metadata"
            if route_not_found else
            "keep reject; reduce slippage or widen execution buffer"
            if slippage_too_high or price_impact_too_high else
            "cooldown RPC or lock venue until health recovers"
            if rpc_degraded else
            "fix wallet / signing readiness"
            if wallet_not_ready else
            "quote path is failing; inspect Jupiter endpoint and route inputs"
        ),
        "rpc_status": str(rpc_health.get("status") or ""),
        "route_status": str(phantom.get("source_status") or ""),
        "wallet_status": "READY" if bool(wallet.get("pubkey") or wallet.get("public_key") or wallet.get("owner")) else "NOT_READY",
        "source_snapshot": {
            "treasury": treasury,
            "quote_state": quote_state,
            "rpc_health": rpc_health,
        },
    }
    out = STATE_DIR / "phantom_quote_diagnosis.json"
    out.write_text(json.dumps(diagnosis, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(diagnosis, indent=2, ensure_ascii=False))
    print(f"status_marker=OK:PHANTOM_QUOTE_DIAGNOSIS status={status}")


if __name__ == "__main__":
    main()

