from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from Core.Support.ki_config import STATE_DIR
from Core.Support.round_trip_accounting import _normalize_symbol


POLICY_FILE = Path("config/strategy_controls/strategy_control_policy.json")
OUTPUT_FILE = STATE_DIR / "strategy_control_actions.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else default
    except Exception:
        return default
    return default


def build_strategy_control_actions(bundle: Dict[str, Any] | None = None) -> Dict[str, Any]:
    bundle = bundle or {}
    policy = _read_json(POLICY_FILE, {})
    strategy_rows = (bundle.get("strategy_edge_audit", {}) or {}).get("strategies", [])
    disabled_pairs: List[str] = []
    do_not_scale_pairs: List[str] = []
    micro_probe_pairs: List[str] = []
    ignored_unknown_source_scaleups: List[str] = []

    for row in strategy_rows if isinstance(strategy_rows, list) else []:
        pair = _normalize_symbol(row.get("strategy") or row.get("pair") or "")
        status = str(row.get("status") or "").upper()
        recommendation = str(row.get("recommendation") or "").upper()
        venue = str(row.get("venue") or "unknown").lower()
        source = str(row.get("source") or row.get("source_quality") or "").lower()
        if status in {"NEGATIVE_EDGE", "CONFLICTED_EDGE"} or recommendation == "DISABLE":
            if pair:
                disabled_pairs.append(pair)
                do_not_scale_pairs.append(pair)
        elif status == "INSUFFICIENT_DATA":
            if pair and pair not in micro_probe_pairs:
                micro_probe_pairs.append(pair)
        if source == "unknown" and recommendation in {"SCALE_UP", "SCALE"} and pair:
            ignored_unknown_source_scaleups.append(pair)
            if pair not in do_not_scale_pairs:
                do_not_scale_pairs.append(pair)
        if venue == "phantom" and "0" in str(row.get("filled_count") or row.get("sample_size") or ""):
            if pair and pair not in do_not_scale_pairs:
                do_not_scale_pairs.append(pair)

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "policy": policy,
        "disabled_pairs": sorted(set(disabled_pairs)),
        "do_not_scale_pairs": sorted(set(do_not_scale_pairs)),
        "micro_probe_pairs": sorted(set(micro_probe_pairs)),
        "ignored_unknown_source_scaleups": sorted(set(ignored_unknown_source_scaleups)),
        "reason": "verified negative edge or conflicted source",
    }
    OUTPUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload

