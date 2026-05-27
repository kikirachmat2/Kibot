from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from Core.Scanner.source_proof import SourceProof

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "indodax_top_targets.json"


def _read(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _score_candidate(item: Dict[str, Any]) -> float:
    volume = float(item.get("volume_24h_idr") or item.get("volume_idr") or 0.0)
    change = float(item.get("change_24h_pct") or item.get("change_pct") or 0.0)
    spread = float(item.get("spread_pct") or 0.0)
    liquidity = float(item.get("liquidity_score") or 0.0)
    score = change * 2.0 + min(volume / 100_000_000.0, 10.0) * 8.0 + liquidity
    if volume >= 200_000_000:
        score += 10.0
    if change > 10:
        score += 6.0
    if spread > 2.5:
        score -= spread * 4.0
    return score


def _iter_source_pools(scan: Dict[str, Any]) -> List[tuple[str, List[Dict[str, Any]]]]:
    pools = [
        ("candidates", scan.get("candidates", []) or []),
        ("approved_candidates", scan.get("approved_candidates", []) or []),
        ("brutal_momentum_candidates", scan.get("brutal_momentum_candidates", []) or []),
        ("pullback_candidates", scan.get("pullback_candidates", []) or []),
        ("leadlag_candidates", scan.get("leadlag_candidates", []) or []),
        ("leadlag_watchlist", scan.get("leadlag_watchlist", []) or []),
        ("volume_leaders", scan.get("volume_leaders", []) or []),
        ("gainers_24h", scan.get("gainers_24h", []) or []),
    ]
    normalized: List[tuple[str, List[Dict[str, Any]]]] = []
    for pool_name, items in pools:
        if isinstance(items, list):
            normalized.append((pool_name, [item for item in items if isinstance(item, dict)]))
    return normalized


def _build_candidate(item: Dict[str, Any], source_pool: str) -> Dict[str, Any]:
    pair = str(item.get("pair") or item.get("symbol") or "").lower()
    symbol = str(item.get("symbol") or pair).upper()
    c = {
        "rank": 0,
        "symbol": symbol,
        "pair": pair.upper(),
        "last_price": float(item.get("last_price") or item.get("price") or 0.0),
        "change_24h_pct": float(item.get("change_24h_pct") or item.get("change_pct") or 0.0),
        "volume_24h_idr": float(item.get("volume_idr") or item.get("volume_24h_idr") or 0.0),
        "spread_pct": float(item.get("spread_pct") or 0.0),
        "momentum_score": float(item.get("change_24h_pct") or item.get("change_pct") or item.get("momentum_score") or 0.0),
        "liquidity_score": float(
            item.get("liquidity_score")
            or item.get("volume_idr")
            or item.get("volume_24h_idr")
            or 0.0
        ) / 100_000_000.0,
        "entry_score": float(item.get("entry_score") or 0.0),
        "exit_score": 0.0,
        "source_proof_ok": bool(SourceProof.validate(item.get("source_proof", {}))) if isinstance(item, dict) else False,
        "route_status": str(item.get("route_status") or "EXECUTABLE"),
        "recommended_action": str(item.get("recommended_action") or "WATCH"),
        "reason": str(item.get("reason") or ""),
        "source_pool": source_pool,
        "is_maintenance": bool(item.get("is_maintenance", False)),
        "is_market_suspended": bool(item.get("is_market_suspended", False)),
        "pair_metadata": item.get("pair_metadata", {}) if isinstance(item.get("pair_metadata"), dict) else {},
        "high_24h": float(item.get("high_24h") or 0.0),
        "low_24h": float(item.get("low_24h") or 0.0),
        "range_position_pct": float(item.get("range_position_pct") or 0.0),
        "distance_to_high_pct": float(item.get("distance_to_high_pct") or 0.0),
        "runup_from_low_pct": float(item.get("runup_from_low_pct") or 0.0),
        "leadlag_gap_pct": float(item.get("leadlag_gap_pct") or 0.0),
        "leadlag_lag_seconds": float(item.get("leadlag_lag_seconds") or 0.0),
        "leadlag_score": float(item.get("leadlag_score") or 0.0),
        "expected_net_pct": float(item.get("expected_net_pct") or 0.0),
        "leader_change_pct": float(item.get("leader_change_pct") or 0.0),
        "follower_change_pct": float(item.get("follower_change_pct") or 0.0),
        "source_pools": [source_pool],
    }
    is_leadlag_pool = source_pool in {"leadlag_candidates", "leadlag_watchlist"}
    if c["entry_score"] <= 0.0:
        c["entry_score"] = _score_candidate(c)
    if source_pool in {"candidates", "approved_candidates"}:
        c["entry_score"] += 4.0
    elif source_pool in {"brutal_momentum_candidates", "pullback_candidates"}:
        c["entry_score"] += 2.0
    elif is_leadlag_pool:
        c["entry_score"] += 12.0
        if str(item.get("recommended_action") or "").upper() == "ENTER":
            c["entry_score"] += 12.0
        if c["leadlag_gap_pct"] >= 0.15:
            c["entry_score"] += 4.0
        if c["leadlag_lag_seconds"] >= 0.5:
            c["entry_score"] += 3.0
    elif source_pool == "volume_leaders":
        c["entry_score"] += 1.0
    if c["range_position_pct"] >= 60.0:
        c["entry_score"] += 2.0
    elif c["range_position_pct"] <= 30.0 and c["runup_from_low_pct"] >= 6.0:
        c["entry_score"] += 1.5
    if c["leadlag_gap_pct"] > 0:
        c["entry_score"] += min(3.0, c["leadlag_gap_pct"] * 1.5)
    if c["leadlag_lag_seconds"] > 0:
        c["entry_score"] += min(2.5, c["leadlag_lag_seconds"] * 0.3)
    c["entry_score"] = round(c["entry_score"], 2)
    c["exit_score"] = round(max(0.0, c["liquidity_score"] - c["spread_pct"]), 2)
    c["priority_boost"] = 0.0
    if is_leadlag_pool:
        c["priority_boost"] += 20.0
        if c["recommended_action"] == "ENTER":
            c["priority_boost"] += 10.0
        if c["leadlag_gap_pct"] >= 0.15:
            c["priority_boost"] += 4.0
        if c["leadlag_lag_seconds"] >= 0.5:
            c["priority_boost"] += 3.0
    elif source_pool in {"candidates", "approved_candidates"}:
        c["priority_boost"] += 6.0
    elif source_pool in {"brutal_momentum_candidates", "pullback_candidates"}:
        c["priority_boost"] += 4.0
    return c


def build_indodax_target_board() -> Dict[str, Any]:
    scan = _read(STATE_DIR / "indodax_scanner_state.json", {})
    candidates_map: Dict[str, Dict[str, Any]] = {}
    source_breakdown: Dict[str, Dict[str, Any]] = {}
    for pool_name, items in _iter_source_pools(scan):
        source_breakdown[pool_name] = {
            "count": len(items),
            "status": "OK" if items else "NO_DATA",
            "reason": "" if items else f"no_candidates_in_{pool_name}",
        }
        for item in items:
            c = _build_candidate(item, pool_name)
            key = c["pair"] or c["symbol"]
            existing = candidates_map.get(key)
            if existing:
                source_pools = list(dict.fromkeys((existing.get("source_pools") or []) + c.get("source_pools", [])))
                if c["entry_score"] > float(existing.get("entry_score", 0.0) or 0.0) or (
                    c["route_status"] == "EXECUTABLE" and existing.get("route_status") != "EXECUTABLE"
                ):
                    c["source_pools"] = source_pools
                    candidates_map[key] = c
                else:
                    existing["source_pools"] = source_pools
                    candidates_map[key] = existing
            else:
                candidates_map[key] = c

    candidates = list(candidates_map.values())
    rejected = {}
    for c in candidates:
        if c.get("is_maintenance") or c.get("is_market_suspended"):
            c["route_status"] = "BLOCKED_WITH_REASON"
            c["recommended_action"] = "REJECT"
            c["reason"] = c["reason"] or (
                f"pair_unavailable_maintenance={int(bool(c.get('is_maintenance')))}_"
                f"suspended={int(bool(c.get('is_market_suspended')))}"
            )
        elif not c["source_proof_ok"]:
            c["route_status"] = "BLOCKED_WITH_REASON"
            c["recommended_action"] = "REJECT"
            c["reason"] = "source_proof_missing_or_invalid"
        elif c["volume_24h_idr"] <= 0:
            c["route_status"] = "BLOCKED_WITH_REASON"
            c["recommended_action"] = "REJECT"
            c["reason"] = "no_real_volume"
        elif c["exit_score"] < (0.25 if c.get("source_pool") in {"leadlag_candidates", "leadlag_watchlist"} else 0.5):
            c["route_status"] = "BLOCKED_WITH_REASON"
            c["recommended_action"] = "REJECT"
            c["reason"] = "exit_liquidity_too_thin"

    candidates.sort(
        key=lambda x: (
            x.get("priority_boost", 0.0),
            x["entry_score"],
            x["leadlag_gap_pct"],
            x["volume_24h_idr"],
            x["change_24h_pct"],
        ),
        reverse=True,
    )
    top_targets: List[Dict[str, Any]] = []
    for idx, item in enumerate(candidates[:5], start=1):
        item = dict(item)
        item["rank"] = idx
        if item["route_status"] == "EXECUTABLE":
            is_leadlag_pool = item.get("source_pool") in {"leadlag_candidates", "leadlag_watchlist"}
            if is_leadlag_pool:
                if item.get("leadlag_gap_pct", 0.0) >= 0.15 and item.get("leadlag_lag_seconds", 0.0) >= 0.5 and item["exit_score"] >= 0.25:
                    item["recommended_action"] = "ENTER"
                elif item["entry_score"] >= 10 and item["exit_score"] >= 0.25:
                    item["recommended_action"] = "ENTER"
                else:
                    item["recommended_action"] = "WATCH"
            else:
                item["recommended_action"] = "ENTER" if item["entry_score"] >= 15 and item["exit_score"] >= 0.5 else "WATCH"
                if item["volume_24h_idr"] < 200_000_000:
                    item["recommended_action"] = "WATCH"
                    item["reason"] = item["reason"] or "below_volume_preference"
                if item["exit_score"] < 1.0:
                    item["recommended_action"] = "WATCH"
                    item["reason"] = item["reason"] or "thin_exit_liquidity"
                if item.get("range_position_pct", 0.0) >= 60.0 and item["change_24h_pct"] >= 5.0:
                    item["recommended_action"] = "ENTER"
                elif item.get("runup_from_low_pct", 0.0) >= 6.0 and item["change_24h_pct"] >= 4.0:
                    item["recommended_action"] = "ENTER"
                elif (
                    item.get("leadlag_gap_pct", 0.0) > 0
                    and item.get("leadlag_lag_seconds", 0.0) > 0
                    and item.get("source_pool") not in {"leadlag_candidates", "leadlag_watchlist"}
                ):
                    item["recommended_action"] = "WATCH"
        top_targets.append(item)

    why_empty = ""
    any_source_data = any(info.get("count", 0) for info in source_breakdown.values())
    source_status = "OK" if (top_targets or any_source_data) else (scan.get("source_status") or "NO_DATA")
    if not top_targets:
        if any_source_data:
            why_empty = "real_indodax_market_data_available_but_no_candidate_met_entry_filters"
        else:
            why_empty = scan.get("no_data_reason") or "no_indodax_candidates_after_source_proof_and_liquidity_filters"
        if scan.get("source_status") not in {"OK", "NO_DATA", "SOURCE_FAILED"}:
            source_status = "BLOCKED_WITH_REASON"

    board = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "age_s": 0,
        "engine": "indodax",
        "source_status": source_status,
        "pairs_checked": int(scan.get("pairs_checked", 0) or 0),
        "categories_checked": scan.get("categories_checked", []),
        "source_breakdown": source_breakdown,
        "minimum_volume_idr_preference": 200000000,
        "top_targets": top_targets,
        "top_gainers": scan.get("gainers_24h", [])[:5],
        "volume_leaders": scan.get("volume_leaders", [])[:5],
        "brutal_momentum": scan.get("brutal_momentum_candidates", [])[:5],
        "rejected_summary": {
            "count": len(scan.get("rejected_candidates", []) or []),
            "reason": scan.get("no_data_reason") or "",
        },
        "why_empty": why_empty,
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(board, indent=2, ensure_ascii=False), encoding="utf-8")
    return board


if __name__ == "__main__":
    print(json.dumps(build_indodax_target_board(), indent=2, ensure_ascii=False))
