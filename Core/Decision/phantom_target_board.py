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
    return {
        "rank": 0,
        "route": str(item.get("route") or item.get("route_type") or item.get("network") or "").lower() or "unknown",
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
    }


def build_phantom_target_board() -> Dict[str, Any]:
    treasury = _read(STATE_DIR / "phantom_treasury.json", {})
    mover = _read(STATE_DIR / "phantom_capital_mover.json", {})
    maximizer = _read(STATE_DIR / "phantom_network_maximizer.json", {})
    scanner_contract = _read(STATE_DIR / "scanner_executor_contract.json", {})
    web3 = _read(STATE_DIR / "web3_opportunities.json", {})
    pumpfun = _read(STATE_DIR / "pumpfun_candidates.json", {})
    market = _read(STATE_DIR / "market_wide_wave_candidates.json", {})
    base = _read(STATE_DIR / "base_scanner_state.json", {})
    future = _read(STATE_DIR / "future_web3_scanner_state.json", {})
    poly = _read(STATE_DIR / "polymarket_scanner_state.json", {})

    routes: List[Dict[str, Any]] = []
    for src in [web3.get("best_opportunities", []), pumpfun.get("candidates", []), market.get("candidates", []), base.get("candidates", []), future.get("candidates", []), poly.get("candidates", [])]:
        if isinstance(src, list):
            for item in src:
                if isinstance(item, dict):
                    routes.append(_normalize_route(item))

    ranked_routes = []
    executable_routes = []
    blocked_routes = {}
    for route in routes:
        reason = ""
        if not route["source_proof_ok"]:
            reason = "source_proof_missing"
        elif not route["quote_ok"]:
            reason = "no_quote"
        elif not route["exit_route_ok"]:
            reason = "no_exit_route"
        elif route["executor_status"].upper().startswith("BLOCKED"):
            reason = route["reason"] or "executor_blocked"
        candidate = dict(route)
        if reason:
            candidate["executor_status"] = "BLOCKED_WITH_REASON"
            candidate["reason"] = reason
            candidate["recommended_action"] = "REJECT" if reason not in {"manual_transfer_required"} else "MANUAL_TRANSFER_REQUIRED"
            blocked_routes.setdefault(route["route"], []).append(candidate)
        else:
            candidate["executor_status"] = "EXECUTABLE"
            candidate["recommended_action"] = "ENTER" if candidate["wave_score"] >= 10 else "WATCH"
            executable_routes.append(candidate)
        ranked_routes.append(candidate)

    executable_routes.sort(key=lambda x: (x["wave_score"], x["volume_or_liquidity"], x["change_pct"]), reverse=True)
    ranked_routes.sort(key=lambda x: (x["wave_score"], x["volume_or_liquidity"], x["change_pct"]), reverse=True)
    top_targets: List[Dict[str, Any]] = []
    for idx, item in enumerate(ranked_routes[:5], start=1):
        item = dict(item)
        item["rank"] = idx
        top_targets.append(item)

    source_status = "OK" if top_targets else ("NO_DATA" if not routes else "BLOCKED_WITH_REASON")
    why_empty = "" if top_targets else "no_phantom_candidates_after_source_proof_checks"

    sol_idr = float(treasury.get("buckets", {}).get("swap_idr", treasury.get("sol_balance_idr", 0.0)) or 0.0)
    base_idrx = float(treasury.get("buckets", {}).get("base_idrx_idr", treasury.get("base_idrx_balance_idr", 0.0)) or 0.0)
    board = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "phantom",
        "source_status": source_status,
        "available_balances": {"solana_sol_idr": sol_idr, "base_idrx_idr": base_idrx},
        "executable_routes": [r["route"] for r in executable_routes],
        "blocked_routes": blocked_routes,
        "top_targets": top_targets,
        "why_empty": why_empty,
        "scanner_executor_contract": scanner_contract,
        "capital_mover": mover,
        "network_maximizer": maximizer,
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(board, indent=2, ensure_ascii=False), encoding="utf-8")
    return board


if __name__ == "__main__":
    print(json.dumps(build_phantom_target_board(), indent=2, ensure_ascii=False))
