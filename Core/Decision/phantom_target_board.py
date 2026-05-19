from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "phantom_top_targets.json"


def _read(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _normalize_route(item: Dict[str, Any]) -> Dict[str, Any]:
    route = str(item.get("route") or item.get("route_type") or item.get("network") or "").lower() or "unknown"
    sector = str(item.get("sector") or "").lower()
    if sector == "pumpfun_bonding_curve":
        route = "pumpfun_native"
    elif sector == "pumpfun_migrated":
        route = "pumpfun_jupiter"
    elif sector == "jupiter_routable":
        route = "solana_jupiter"
    elif sector == "solana_meme":
        route = "solana_meme"
    elif str(item.get("chain") or item.get("network") or item.get("venue") or "").lower() == "base":
        route = "base_swap"
    elif sector == "polymarket":
        route = "polymarket"
    elif route == "unknown" and str(item.get("chain") or "").lower() in {"solana", "base", "polygon"}:
        route = {
            "solana": "solana_jupiter",
            "base": "base_swap",
            "polygon": "polymarket",
        }.get(str(item.get("chain") or "").lower(), "future_web3")

    return {
        "rank": 0,
        "route": route,
        "symbol": str(item.get("symbol") or item.get("asset") or item.get("market") or item.get("name") or "").upper(),
        "mint_or_market": str(item.get("mint") or item.get("market_id") or item.get("market") or "").strip(),
        "chain": str(item.get("chain") or item.get("network") or item.get("venue") or "").lower(),
        "price": float(item.get("price") or item.get("last_price") or 0.0),
        "change_pct": float(item.get("change_pct") or item.get("change_24h_pct") or item.get("change_5m_pct") or 0.0),
        "volume_or_liquidity": float(item.get("liquidity_usd") or item.get("volume_24h_usd") or item.get("volume_1h_usd") or item.get("volume") or 0.0),
        "wave_phase": str(item.get("wave_phase") or item.get("phase") or "WATCH"),
        "wave_score": float(item.get("wave_score") or item.get("momentum_score") or 0.0),
        "quote_ok": bool(item.get("quote_ok", item.get("route_available", False))),
        "exit_route_ok": bool(item.get("exit_route_ok", item.get("sell_route_available", False))),
        "source_proof_ok": bool(item.get("source_proof_ok", item.get("source_proof", {}).get("proof_ok", False))),
        "executor_status": str(item.get("executor_status") or item.get("status") or "BLOCKED_WITH_REASON"),
        "recommended_action": str(item.get("recommended_action") or "WATCH"),
        "reason": str(item.get("reason") or ""),
        "advisory_notes": list(item.get("advisory_notes") or []),
    }


def _extract_candidates(payload: Any, keys: List[str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    if not isinstance(payload, dict):
        return results
    for key in keys:
        val = payload.get(key, [])
        if isinstance(val, dict):
            val = list(val.values())
        if isinstance(val, list):
            results.extend([item for item in val if isinstance(item, dict)])
    return results


def build_phantom_target_board() -> Dict[str, Any]:
    treasury = _read(STATE_DIR / "phantom_treasury.json", {})
    mover = _read(STATE_DIR / "phantom_capital_mover.json", {})
    maximizer = _read(STATE_DIR / "phantom_network_maximizer.json", {})
    scanner_contract = _read(STATE_DIR / "scanner_executor_contract.json", {})
    web3 = _read(STATE_DIR / "web3_opportunities.json", {})
    pumpfun = _read(STATE_DIR / "pumpfun_candidates.json", {})
    pumpfun_wave = _read(STATE_DIR / "pumpfun_wave_candidates.json", {})
    market = _read(STATE_DIR / "market_wide_wave_candidates.json", {})
    base = _read(STATE_DIR / "base_scanner_state.json", {})
    future = _read(STATE_DIR / "future_web3_scanner_state.json", {})
    poly = _read(STATE_DIR / "polymarket_scanner_state.json", {})
    sol_jup = _read(STATE_DIR / "solana_jupiter_scanner_state.json", {})
    sol_meme = _read(STATE_DIR / "solana_meme_scanner_state.json", {})

    source_map = {
        "market_wide_real_candidates": (market, ["real_candidates", "approved_candidates", "hot_waves", "best_candidates"]),
        "pumpfun_wave": (pumpfun_wave, ["new_launches", "early_pumps", "migrated_candidates", "jupiter_routable_candidates", "approved_candidates", "best_wave"]),
        "pumpfun_candidates": (pumpfun, ["candidates", "approved_candidates", "best_candidate"]),
        "solana_jupiter": (sol_jup, ["candidates", "approved_candidates", "best_candidate"]),
        "solana_meme": (sol_meme, ["candidates", "approved_candidates", "best_candidate"]),
        "base_swap": (base, ["candidates", "approved_candidates", "best_candidate"]),
        "future_web3": (future, ["candidates", "approved_candidates", "best_candidate"]),
        "polymarket": (poly, ["candidates", "approved_candidates", "best_candidate"]),
        "web3": (web3, ["best_opportunities", "meme_hunter", "opportunities"]),
    }

    route_capabilities: Dict[str, Dict[str, Any]] = {}
    for route in scanner_contract.get("routes", []) if isinstance(scanner_contract, dict) else []:
        if not isinstance(route, dict):
            continue
        route_capabilities[str(route.get("route") or "").lower()] = {
            "can_scan": bool(route.get("can_scan", False)),
            "can_quote": bool(route.get("can_quote", False)),
            "can_execute": bool(route.get("can_execute", False)),
            "can_exit": bool(route.get("can_exit", False)),
            "status": str(route.get("status") or "UNKNOWN"),
            "reason": str(route.get("reason") or ""),
        }

    routes: List[Dict[str, Any]] = []
    source_breakdown: Dict[str, Dict[str, Any]] = {}
    for source_name, (payload, keys) in source_map.items():
        raw_items = _extract_candidates(payload, keys)
        normalized: List[Dict[str, Any]] = []
        for item in raw_items:
            candidate = _normalize_route(item)
            candidate["source_file"] = source_name
            if source_name == "market_wide_real_candidates":
                candidate["route"] = str(item.get("route") or item.get("sector") or candidate["route"])
            if item.get("sector") == "pumpfun_bonding_curve":
                candidate["route"] = "pumpfun_native"
            elif item.get("sector") == "pumpfun_migrated":
                candidate["route"] = "pumpfun_jupiter"
            elif item.get("sector") == "jupiter_routable":
                candidate["route"] = "solana_jupiter"
            elif item.get("sector") == "solana_meme":
                candidate["route"] = "solana_meme"
            elif str(candidate.get("chain", "")).lower() == "base":
                candidate["route"] = "base_swap"
            elif item.get("sector") == "polymarket":
                candidate["route"] = "polymarket"
            else:
                candidate["route"] = candidate["route"] if candidate["route"] != "unknown" else "future_web3"
            normalized.append(candidate)
        routes.extend(normalized)
        source_breakdown[source_name] = {"count": len(normalized), "status": "OK" if normalized else "NO_DATA", "reason": "" if normalized else f"no_candidates_in_{source_name}"}

    ranked_routes = []
    executable_routes = []
    blocked_routes = {}
    for route in routes:
        reason = ""
        route_caps = route_capabilities.get(route["route"], {})
        route_exec_ready = bool(route_caps.get("can_execute"))
        route_exit_ready = bool(route_caps.get("can_exit"))
        if not route["source_proof_ok"]:
            reason = "source_proof_missing"
        elif not route_exit_ready:
            reason = "no_exit_route"
        elif route_caps.get("status", "").upper().startswith("BLOCKED") and not route_exec_ready:
            reason = route_caps.get("reason") or route["reason"] or "executor_blocked"
        candidate = dict(route)
        advisory_notes = list(candidate.get("advisory_notes") or [])
        if not candidate["quote_ok"]:
            advisory_notes.append("no_quote")
        candidate["advisory_notes"] = sorted(set(advisory_notes))
        if reason:
            candidate["executor_status"] = "BLOCKED_WITH_REASON"
            candidate["reason"] = reason
            candidate["recommended_action"] = "REJECT" if reason not in {"manual_transfer_required"} else "MANUAL_TRANSFER_REQUIRED"
            blocked_routes.setdefault(route["route"], []).append(candidate)
        else:
            candidate["executor_status"] = "EXECUTABLE"
            if not candidate["quote_ok"]:
                candidate["recommended_action"] = "WATCH"
                if "no_quote" not in candidate["advisory_notes"]:
                    candidate["advisory_notes"].append("no_quote")
            else:
                candidate["recommended_action"] = "ENTER" if candidate["wave_score"] >= 10 else "WATCH"
            executable_routes.append(candidate)
        ranked_routes.append(candidate)

    def route_priority(route: str) -> int:
        route = str(route or "").lower()
        if route in {"solana_jupiter", "pumpfun_jupiter"}:
            return 5
        if route in {"pumpfun_native"}:
            return 4
        if route in {"base_swap"}:
            return 4
        if route in {"solana_meme"}:
            return 3
        if route in {"polymarket"}:
            return 2
        return 1

    executable_routes.sort(key=lambda x: (route_priority(x["route"]), x["wave_score"], x["volume_or_liquidity"], x["change_pct"]), reverse=True)
    ranked_routes.sort(key=lambda x: (route_priority(x["route"]), x["wave_score"], x["volume_or_liquidity"], x["change_pct"]), reverse=True)
    top_targets: List[Dict[str, Any]] = []
    for idx, item in enumerate(ranked_routes[:5], start=1):
        item = dict(item)
        item["rank"] = idx
        top_targets.append(item)

    source_status = "OK" if top_targets else ("NO_DATA" if not routes else "BLOCKED_WITH_REASON")
    why_empty = "" if top_targets else "no_phantom_candidates_after_source_proof_checks"
    if not any(v["count"] for v in source_breakdown.values()):
        source_status = "NO_DATA"
        why_empty = "all phantom source feeds empty or stale"

    sol_idr = float(treasury.get("buckets", {}).get("swap_idr", treasury.get("sol_balance_idr", 0.0)) or 0.0)
    base_idrx = float(treasury.get("buckets", {}).get("base_idrx_idr", treasury.get("base_idrx_balance_idr", 0.0)) or 0.0)
    board = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "phantom",
        "source_status": source_status,
        "source_breakdown": source_breakdown,
        "available_balances": {"solana_sol_idr": sol_idr, "base_idrx_idr": base_idrx},
        "executable_routes": [r["route"] for r in executable_routes],
        "blocked_routes": blocked_routes,
        "top_targets": top_targets,
        "why_empty": why_empty,
        "route_capabilities": route_capabilities,
        "scanner_executor_contract": scanner_contract,
        "capital_mover": mover,
        "network_maximizer": maximizer,
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(board, indent=2, ensure_ascii=False), encoding="utf-8")
    return board


if __name__ == "__main__":
    print(json.dumps(build_phantom_target_board(), indent=2, ensure_ascii=False))
