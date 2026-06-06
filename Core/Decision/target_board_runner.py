from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from Core.Decision.indodax_target_board import build_indodax_target_board
from Core.Decision.engine_independence import write_engine_independence
from Core.Scanner.scanner_executor_contract import ScannerExecutorContract
from Core.Support.ki_config import KiConfig

logger = logging.getLogger("TargetBoardRunner")
STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "target_board_runtime.json"


def _read_json(path: Path, default):
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, type(default)) or isinstance(payload, dict) else default
    except Exception:
        pass
    return default


def _normalize_phantom_candidate(target: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "updated_at": now,
        "timestamp_wib": now,
        "event_type": "CANDIDATE_STAGED",
        "trade_event_type": "CANDIDATE_STAGED",
        "venue": "phantom",
        "route": str(target.get("route") or target.get("route_type") or target.get("chain") or "phantom").lower(),
        "symbol": str(target.get("symbol") or target.get("asset") or target.get("market") or "").upper(),
        "pair": str(target.get("symbol") or target.get("asset") or target.get("market") or "").upper(),
        "tier": str(target.get("tier") or target.get("label") or "WATCH"),
        "status": "STAGED",
        "reason": str(target.get("reason") or target.get("recommended_action") or "staged_from_phantom_targets"),
        "approved": bool(str(target.get("recommended_action") or "").upper() == "ENTER"),
        "confidence": float(target.get("confidence") or 0.0),
        "expected_net_edge_pct": float(target.get("expected_net_edge_pct") or 0.0),
        "historical_sample_size": int(float(target.get("historical_sample_size") or 0)),
        "source_proof_ok": bool(target.get("source_proof_ok", False)),
        "min_sellable_pass": bool(target.get("exit_route_ok", False)),
        "partial_tp_feasible": bool(target.get("exit_route_ok", False)),
        "exit_depth_pass": bool(target.get("exit_route_ok", False)),
        "simulation_verdict": "PASS" if bool(target.get("exit_route_ok", False)) and bool(target.get("source_proof_ok", False)) else "REJECT",
        "max_spread_pct": float(target.get("max_spread_pct") or 1.0),
        "max_slippage_pct": float(target.get("max_slippage_pct") or 1.2),
        "pair_quarantine": "",
        "exit_plan_valid": bool(target.get("exit_route_ok", False)),
        "micro_probe_requested": True,
        "scale_up_requested": False,
    }


def _write_candidate_decisions(phantom: dict) -> None:
    candidate_path = STATE_DIR / "candidate_decisions.jsonl"
    existing: List[Dict[str, Any]] = []
    if candidate_path.exists():
        for line in candidate_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                if isinstance(payload, dict):
                    existing.append(payload)
            except Exception:
                continue
    staged = [row for row in existing if str(row.get("venue") or "").lower() != "phantom"]
    for target in phantom.get("top_targets", []) or []:
        if isinstance(target, dict):
            staged.append(_normalize_phantom_candidate(target))
    candidate_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in staged) + ("\n" if staged else ""), encoding="utf-8")


def _venue_engine_state(governor: dict, venue_key: str, source_status: str, source_reason: str) -> dict:
    venues = governor.get("venues", {}) if isinstance(governor, dict) else {}
    venue = venues.get(venue_key, {}) if isinstance(venues, dict) else {}
    allow_orders = bool(venue.get("allow_orders", False))
    venue_status = str(venue.get("status") or "").upper()
    status = "ACTIVE" if source_status == "OK" and allow_orders else "BLOCKED_WITH_REASON"
    reason = str(venue.get("reason") or source_reason or "")
    if not source_status == "OK":
        reason = reason or f"{venue_key}_scanner_source_failed"
    elif not allow_orders:
        reason = reason or f"{venue_key}_orders_blocked"
    return {
        "status": status,
        "scanner": "ACTIVE" if source_status == "OK" else "BLOCKED_WITH_REASON",
        "executor": "ACTIVE" if allow_orders else "BLOCKED_WITH_REASON",
        "allow_orders": allow_orders,
        "reason": reason,
        "source_status": source_status,
        "source_reason": source_reason,
        "venue_status": venue_status,
    }


def _write_runtime(indodax: dict, phantom: dict, error: str = "") -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "loop_interval_seconds": 5,
        "indodax_updated": bool(indodax),
        "phantom_updated": False,
        "indodax_count": len(indodax.get("top_targets", []) or []),
        "phantom_count": 0,
        "platform_mode": "INDODAX_ONLY" if KiConfig.INDODAX_ONLY else "MULTI_VENUE",
        "errors": {"last_error": error} if error else {},
    }
    STATE_FILE.write_text(__import__("json").dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


async def run_forever() -> None:
    while True:
        try:
            indo = build_indodax_target_board()
            ph = {}
            ScannerExecutorContract().write_contract_state()
            if not KiConfig.INDODAX_ONLY:
                from Core.Decision.phantom_target_board import build_phantom_target_board
                from Core.Treasury.phantom_capital_mover import write_phantom_capital_mover
                from Core.Treasury.phantom_network_maximizer import write_phantom_network_maximizer

                ph = build_phantom_target_board()
                write_phantom_capital_mover({})
                write_phantom_network_maximizer({})
                _write_candidate_decisions(ph)
            governor = _read_json(STATE_DIR / "capital_governor.json", {})
            indodax_state = _venue_engine_state(
                governor,
                "indodax",
                str(indo.get("source_status") or "NO_DATA").upper(),
                str(indo.get("why_empty") or indo.get("no_data_reason") or ""),
            )
            phantom_state = {
                "status": "REMOVED_BY_OPERATOR",
                "scanner": "REMOVED_BY_OPERATOR",
                "executor": "REMOVED_BY_OPERATOR",
                "allow_orders": False,
                "reason": "operator_removed_compromised_wallet_use_indodax_only",
            }
            write_engine_independence({
                "indodax_engine": indodax_state,
                "phantom_engine": phantom_state,
                "bridge": "OFF",
                "withdrawal": "OFF",
            })
            _write_runtime(indo, ph, "")
        except Exception as exc:  # pragma: no cover
            logger.exception("target board refresh failed: %s", exc)
            _write_runtime({}, {}, str(exc))
        await asyncio.sleep(5)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
