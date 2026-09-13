#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Support.ki_config import STATE_DIR

OUT_FILE = STATE_DIR / "autonomous_runtime_readiness_audit.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, (dict, list)) else default
    except Exception:
        return default
    return default


def _age_s(path: Path) -> float:
    try:
        return round(time.time() - path.stat().st_mtime, 1)
    except Exception:
        return -1.0


import time


def _service_active(name: str) -> bool:
    try:
        proc = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=5, check=False)
        return str(proc.stdout).strip() == "active"
    except Exception:
        return False


def build_autonomous_runtime_readiness_audit() -> Dict[str, Any]:
    services = {
        "kibot-live-truth": _service_active("kibot-live-truth"),
        "kibot-master": _service_active("kibot-master"),
        "kibot-scanner": _service_active("kibot-scanner"),
        "kibot-executor": _service_active("kibot-executor"),
        "kibot-dashboard": _service_active("kibot-dashboard"),
        "kibot-workflow-supervisor": _service_active("kibot-workflow-supervisor"),
        "kibot-ai-scout": _service_active("kibot-ai-scout"),
        "kibot-telemetry": _service_active("kibot-telemetry"),
    }
    live_truth = _read_json(STATE_DIR / "live_truth.json", {})
    no_trade = _read_json(STATE_DIR / "no_trade_forensics.json", {})
    workflow = _read_json(STATE_DIR / "workflow_automation.json", {})
    target_board = _read_json(STATE_DIR / "target_board_runtime.json", {})
    recovery = _read_json(STATE_DIR / "recovery_reset_plan.json", {})
    ai_inventory = _read_json(STATE_DIR / "ai_system_inventory.json", {})
    telemetry = _read_json(STATE_DIR / "server_telemetry.json", {})
    capital = _read_json(STATE_DIR / "capital_governor.json", {})

    service_ok = all(services.values())
    truth_fresh = bool(live_truth.get("updated_at"))
    targets_fresh = _age_s(STATE_DIR / "target_board_runtime.json") >= 0 and _age_s(STATE_DIR / "target_board_runtime.json") < 30
    ai_ready = bool(ai_inventory.get("summary")) and int(ai_inventory.get("summary", {}).get("active_components", 0) or 0) >= 15
    telemetry_fresh = _age_s(STATE_DIR / "server_telemetry.json") >= 0 and _age_s(STATE_DIR / "server_telemetry.json") < 30
    risk_state = str(live_truth.get("risk_state") or no_trade.get("classification") or "UNKNOWN").upper()
    recovery_mode = bool((recovery.get("policy") or {}).get("enabled", False)) or bool((workflow.get("recovery_mode") or {}).get("active", False))
    daily_lock = "daily_loss_cap_breached" in str(capital.get("allow_new_orders_reason") or "").lower()
    ready = service_ok and truth_fresh and targets_fresh and ai_ready and telemetry_fresh
    status = "READY" if ready and risk_state in {"OK", "CAUTION", "LOCKED"} else "LOCKED_BY_RISK" if daily_lock or risk_state in {"LOCKED", "EMERGENCY"} else "DEGRADED"

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "service_ok": service_ok,
        "services": services,
        "live_truth_fresh": truth_fresh,
        "target_board_fresh": targets_fresh,
        "ai_ready": ai_ready,
        "telemetry_fresh": telemetry_fresh,
        "risk_state": risk_state,
        "recovery_mode": recovery_mode,
        "daily_lock": daily_lock,
        "last_reason": str(no_trade.get("movement_reason") or no_trade.get("why_wait") or capital.get("allow_new_orders_reason") or ""),
        "readiness_score": sum([service_ok, truth_fresh, targets_fresh, ai_ready, telemetry_fresh]),
        "sources": {
            "live_truth": live_truth,
            "no_trade_forensics": no_trade,
            "workflow": workflow,
            "target_board_runtime": target_board,
            "recovery_reset_plan": recovery,
            "ai_system_inventory": ai_inventory,
            "server_telemetry": telemetry,
            "capital_governor": capital,
        },
    }
    OUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def main() -> int:
    payload = build_autonomous_runtime_readiness_audit()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"OK:AUTONOMOUS_RUNTIME_READINESS_AUDITED status={payload.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
