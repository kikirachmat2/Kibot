#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Support.ki_config import STATE_DIR

OUT_FILE = STATE_DIR / "target_freshness_audit.json"
HISTORY_FILE = STATE_DIR / "target_freshness_history.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, (dict, list)) else default
    except Exception:
        return default
    return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "None", "nan"):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _file_age_s(path: Path) -> float:
    try:
        if path.exists():
            return round((datetime.now(timezone.utc).timestamp() - path.stat().st_mtime), 1)
    except Exception:
        pass
    return -1.0


def _fingerprint(payload: Any) -> str:
    try:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        raw = repr(payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _target_age(board: Dict[str, Any], state_file: Path) -> float:
    ts = _parse_dt(board.get("updated_at"))
    if ts is not None:
        diff = (datetime.now(timezone.utc) - ts).total_seconds()
        return round(max(0.0, diff), 1)
    return _file_age_s(state_file)


def build_target_freshness_audit() -> Dict[str, Any]:
    indodax_path = STATE_DIR / "indodax_top_targets.json"
    scanner_runtime_path = STATE_DIR / "target_board_runtime.json"
    candidate_path = STATE_DIR / "candidate_decisions.jsonl"
    dashboard_path = STATE_DIR / "control_plane.json"

    indodax = _read_json(indodax_path, {})
    scanner_runtime = _read_json(scanner_runtime_path, {})
    dashboard = _read_json(dashboard_path, {})
    candidate_rows: List[dict] = []
    if candidate_path.exists():
        for line in candidate_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    candidate_rows.append(row)
            except Exception:
                continue

    latest_candidate = candidate_rows[-1] if candidate_rows else {}
    latest_candidate_age_s = -1.0
    if latest_candidate:
        latest_candidate_age_s = _target_age(latest_candidate, candidate_path)

    indodax_age_s = _target_age(indodax if isinstance(indodax, dict) else {}, indodax_path)
    scanner_runtime_age_s = _target_age(scanner_runtime if isinstance(scanner_runtime, dict) else {}, scanner_runtime_path)
    dashboard_target = (dashboard.get("target_board_runtime") or dashboard.get("target_board") or {}) if isinstance(dashboard, dict) else {}
    dashboard_target_age_s = _safe_float(dashboard_target.get("age_s"), _file_age_s(dashboard_path))

    top_targets_changed_last_30m = False
    history = _read_json(HISTORY_FILE, [])
    current_fingerprint = {
        "indodax": _fingerprint(indodax.get("top_targets", []) if isinstance(indodax, dict) else []),
    }
    if isinstance(history, list) and history:
        last = history[-1] if isinstance(history[-1], dict) else {}
        last_fp = last.get("fingerprint") if isinstance(last, dict) else {}
        last_ts = _parse_dt(last.get("updated_at")) if isinstance(last, dict) else None
        if isinstance(last_fp, dict) and last_fp != current_fingerprint:
            top_targets_changed_last_30m = True
        elif last_ts is not None and (datetime.now(timezone.utc) - last_ts).total_seconds() < 1800:
            top_targets_changed_last_30m = True
    else:
        top_targets_changed_last_30m = True

    stale_threshold_s = 300.0
    stale_reasons = []
    if indodax_age_s > stale_threshold_s:
        stale_reasons.append("indodax_target_stale")
    if scanner_runtime_age_s > stale_threshold_s:
        stale_reasons.append("scanner_runtime_stale")
    if dashboard_target_age_s > stale_threshold_s:
        stale_reasons.append("dashboard_target_stale")
    if not candidate_rows:
        stale_reasons.append("candidate_decisions_missing")

    if stale_reasons and dashboard_target_age_s > stale_threshold_s:
        status = "DASHBOARD_STALE_BINDING"
        reason = "dashboard reading stale target state"
        fix = "rebind dashboard to target board freshness and refresh writer"
    elif stale_reasons and (indodax_age_s > stale_threshold_s or scanner_runtime_age_s > stale_threshold_s):
        status = "SCANNER_NOT_WRITING"
        reason = ";".join(stale_reasons)
        fix = "restart or repair scanner/target board writer"
    elif not top_targets_changed_last_30m:
        status = "STUCK"
        reason = "targets unchanged for 30m and freshness window passed"
        fix = "confirm market stability or inspect scanner writer loop"
    else:
        status = "FRESH"
        reason = "target files fresh and writer activity observed"
        fix = "none"

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "indodax_target_age_s": indodax_age_s,
        "scanner_runtime_age_s": scanner_runtime_age_s,
        "latest_candidate_age_s": latest_candidate_age_s,
        "dashboard_target_age_s": dashboard_target_age_s,
        "top_targets_changed_last_30m": bool(top_targets_changed_last_30m),
        "reason": reason,
        "fix": fix,
        "current_fingerprint": current_fingerprint,
        "stale_threshold_s": stale_threshold_s,
        "sources": {
            "indodax": indodax.get("source_status") if isinstance(indodax, dict) else "",
            "scanner_runtime": scanner_runtime,
        },
    }
    OUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    history.append({"updated_at": payload["updated_at"], "fingerprint": current_fingerprint})
    HISTORY_FILE.write_text(json.dumps(history[-12:], indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def main() -> int:
    payload = build_target_freshness_audit()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"OK:TARGET_FRESHNESS_AUDITED status={payload.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
