#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from Core.Decision.indodax_target_board import build_indodax_target_board
from Core.Decision.phantom_target_board import build_phantom_target_board
from Core.Scanner.scanner_health import write_scanner_health
from Core.Runtime.server_telemetry import write_server_telemetry

STATE = Path(__file__).resolve().parent.parent / "state"
CLAIM_FILE = STATE / "final_server_claim.json"


def _read(name: str, default: Any) -> Any:
    p = STATE / name
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _svc(name: str) -> Dict[str, Any]:
    try:
        active = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=8).stdout.strip()
    except Exception as exc:
        active = f"error:{exc}"
    try:
        enabled = subprocess.run(["systemctl", "is-enabled", name], capture_output=True, text=True, timeout=8).stdout.strip()
    except Exception as exc:
        enabled = f"error:{exc}"
    return {"active": active, "enabled": enabled}


def _fresh(path: Path, max_age_s: float = 600.0) -> bool:
    try:
        return path.exists() and (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) <= max_age_s
    except Exception:
        return False


def build_final_claim() -> Dict[str, Any]:
    indodax = build_indodax_target_board()
    phantom = build_phantom_target_board()
    scanner_health = write_scanner_health(_read("scanner_executor_contract.json", {}))
    telemetry = write_server_telemetry({})
    services = {
        name: _svc(name)
        for name in [
            "kibot-capital-governor",
            "kibot-indodax-director",
            "kibot-scanner",
            "kibot-scanner-health",
            "kibot-executor",
            "kibot-pumpfun",
            "kibot-base",
            "kibot-future-web3",
            "kibot-executor-polymarket",
            "kibot-web3-exit",
            "kibot-ai-scout",
            "kibot-dashboard",
            "kibot-cloudflared",
        ]
    }
    service_active = all(v["active"] == "active" for v in services.values())
    service_missing = [k for k, v in services.items() if v["active"] != "active"]
    states = {
        "engine_independence": _fresh(STATE / "engine_independence.json"),
        "capital_governor": _fresh(STATE / "capital_governor.json"),
        "indodax_scanner": _fresh(STATE / "indodax_scanner_state.json"),
        "indodax_no_idle": _fresh(STATE / "indodax_no_idle.json"),
        "indodax_top_targets": _fresh(STATE / "indodax_top_targets.json"),
        "phantom_treasury": _fresh(STATE / "phantom_treasury.json"),
        "phantom_capital_mover": _fresh(STATE / "phantom_capital_mover.json"),
        "phantom_network_maximizer": _fresh(STATE / "phantom_network_maximizer.json"),
        "phantom_top_targets": _fresh(STATE / "phantom_top_targets.json"),
        "deadline_profit_enforcer": _fresh(STATE / "deadline_profit_enforcer.json"),
        "scanner_executor_contract": _fresh(STATE / "scanner_executor_contract.json"),
        "scanner_health": _fresh(STATE / "scanner_health.json"),
        "server_telemetry": _fresh(STATE / "server_telemetry.json"),
        "ai_strategy_review": _fresh(STATE / "ai_strategy_review.json"),
    }
    claim_blocker = ""
    if service_missing:
        claim_blocker = f"inactive_services:{','.join(service_missing)}"
    elif not all(states.values()):
        missing = [k for k, v in states.items() if not v]
        claim_blocker = f"stale_or_missing_states:{','.join(missing)}"
    elif not indodax.get("top_targets"):
        claim_blocker = indodax.get("why_empty") or "indodax_top_targets_empty"
    elif not phantom.get("top_targets"):
        claim_blocker = phantom.get("why_empty") or "phantom_top_targets_empty"
    claim = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=8).stdout.strip(),
        "batam_runtime": "OK" if not claim_blocker else "DEGRADED",
        "services_active": services,
        "states_fresh": states,
        "indodax_engine": _read("engine_independence.json", {}),
        "phantom_engine": _read("phantom_capital_mover.json", {}),
        "top_targets": {"indodax_count": len(indodax.get("top_targets", [])), "phantom_count": len(phantom.get("top_targets", []))},
        "dashboard": {
            "healthz": "http://127.0.0.1:8787/api/healthz",
            "control_plane": "http://127.0.0.1:8787/api/control-plane",
            "public_url_status": "unknown",
        },
        "final_claim_allowed": not bool(claim_blocker),
        "claim_blocker": claim_blocker,
        "server_telemetry": telemetry,
        "scanner_health": scanner_health,
    }
    CLAIM_FILE.write_text(json.dumps(claim, indent=2, ensure_ascii=False), encoding="utf-8")
    return claim


if __name__ == "__main__":
    print(json.dumps(build_final_claim(), indent=2, ensure_ascii=False))
