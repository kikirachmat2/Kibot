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


def build_indodax_target_board() -> Dict[str, Any]:
    scan = _read(STATE_DIR / "indodax_scanner_state.json", {})
    candidates = []
    rejected = {}
    for item in scan.get("gainers_24h", []) or []:
        if isinstance(item, dict):
            pair = str(item.get("pair") or item.get("symbol") or "").lower()
            c = {
                "rank": 0,
                "symbol": str(item.get("symbol") or pair).upper(),
                "pair": pair.upper(),
                "last_price": float(item.get("last_price") or item.get("price") or 0.0),
                "change_24h_pct": float(item.get("change_24h_pct") or 0.0),
                "volume_24h_idr": float(item.get("volume_idr") or item.get("volume_24h_idr") or 0.0),
                "spread_pct": float(item.get("spread_pct") or 0.0),
                "momentum_score": float(item.get("change_24h_pct") or 0.0),
                "liquidity_score": float(item.get("volume_idr") or 0.0) / 100_000_000.0,
                "entry_score": 0.0,
                "exit_score": 0.0,
                "source_proof_ok": bool(SourceProof.validate(item.get("source_proof", {}))) if isinstance(item, dict) else False,
                "route_status": "EXECUTABLE",
                "recommended_action": "WATCH",
                "reason": "",
            }
            c["entry_score"] = round(_score_candidate(c), 2)
            c["exit_score"] = round(c["liquidity_score"] - c["spread_pct"], 2)
            if not c["source_proof_ok"]:
                c["route_status"] = "BLOCKED_WITH_REASON"
                c["recommended_action"] = "REJECT"
                c["reason"] = "source_proof_missing_or_invalid"
            elif c["volume_24h_idr"] <= 0:
                c["route_status"] = "BLOCKED_WITH_REASON"
                c["recommended_action"] = "REJECT"
                c["reason"] = "no_real_volume"
            elif c["exit_score"] < 0.5:
                c["route_status"] = "BLOCKED_WITH_REASON"
                c["recommended_action"] = "REJECT"
                c["reason"] = "exit_liquidity_too_thin"
            candidates.append(c)

    candidates.sort(key=lambda x: (x["entry_score"], x["volume_24h_idr"], x["change_24h_pct"]), reverse=True)
    top_targets: List[Dict[str, Any]] = []
    for idx, item in enumerate(candidates[:5], start=1):
        item = dict(item)
        item["rank"] = idx
        if item["route_status"] == "EXECUTABLE":
            item["recommended_action"] = "ENTER" if item["entry_score"] >= 15 and item["exit_score"] >= 0.5 else "WATCH"
            if item["volume_24h_idr"] < 200_000_000:
                item["recommended_action"] = "WATCH"
                item["reason"] = item["reason"] or "below_volume_preference"
            if item["exit_score"] < 1.0:
                item["recommended_action"] = "WATCH"
                item["reason"] = item["reason"] or "thin_exit_liquidity"
        top_targets.append(item)

    why_empty = ""
    source_status = "OK" if scan.get("source_status") == "OK" and top_targets else scan.get("source_status") or "NO_DATA"
    if not top_targets:
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
