from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "phantom_network_maximizer.json"
TREASURY_FILE = STATE_DIR / "phantom_treasury.json"
TARGETS_FILE = STATE_DIR / "phantom_top_targets.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def write_phantom_network_maximizer(payload: Dict[str, Any]) -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    treasury = _read_json(TREASURY_FILE, {})
    targets = _read_json(TARGETS_FILE, {})
    route_candidates = list(targets.get("top_targets", []) or []) if isinstance(targets, dict) else []
    executable = [
        t
        for t in route_candidates
        if isinstance(t, dict)
        and str(t.get("executor_status") or "").upper() == "EXECUTABLE"
        and bool(t.get("gas_affordable", True))
    ]
    executable.sort(key=lambda x: (
        float(x.get("wave_score") or x.get("entry_score") or 0.0),
        float(x.get("volume_or_liquidity") or x.get("volume_24h_idr") or 0.0),
        float(x.get("change_pct") or x.get("change_24h_pct") or 0.0),
    ), reverse=True)
    best = executable[0] if executable else (route_candidates[0] if route_candidates else {})
    best_route = str(best.get("route") or "")
    if not best_route:
        sol_balance = float(treasury.get("sol_balance") or treasury.get("chains", {}).get("solana", {}).get("sol_balance") or 0.0)
        base_idrx = float(treasury.get("base_idrx_balance") or treasury.get("chains", {}).get("base", {}).get("normalized_idrx") or 0.0)
        if sol_balance > 0:
            best_route = "solana_jupiter"
        elif base_idrx > 0:
            best_route = "base_swap"
    resolved = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "best_route": best_route,
        "best_candidate": best,
        "executable_routes": [str(t.get("route") or "") for t in executable],
        "blocked_routes": {
            str(t.get("route") or f"idx_{idx}"): str(t.get("gas_reason") or t.get("reason") or "route_blocked")
            for idx, t in enumerate(route_candidates)
            if isinstance(t, dict) and not (str(t.get("executor_status") or "").upper() == "EXECUTABLE" and bool(t.get("gas_affordable", True)))
        },
        "recommended_action": "ENTER" if best_route else "SCAN_NEXT",
        "reason": "" if best_route else ("no_executable_phantom_route" if route_candidates else "no_phantom_route_candidates"),
    }
    resolved.update(payload or {})
    if not resolved.get("best_route"):
        resolved["best_route"] = best_route
    if not resolved.get("best_candidate"):
        resolved["best_candidate"] = best
    if not resolved.get("executable_routes"):
        resolved["executable_routes"] = [str(t.get("route") or "") for t in executable]
    STATE_FILE.write_text(json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")
    return resolved
