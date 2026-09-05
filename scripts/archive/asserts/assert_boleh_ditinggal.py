#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / "state"


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
        if path.exists():
            return round(time.time() - path.stat().st_mtime, 1)
    except Exception:
        pass
    return -1.0


import time


def _run(script: str) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(ROOT / script)], capture_output=True, text=True, check=False)
    return proc.returncode, (proc.stdout or proc.stderr or "").strip()


def main() -> int:
    issues: list[str] = []
    checks = {}
    scripts = {
        "live_truth": "scripts/assert_live_truth_writer.py",
        "dashboard": "scripts/assert_dashboard_live_truth.py",
        "target_freshness": "scripts/audit_target_freshness.py",
        "ai_usage": "scripts/audit_ai_actual_usage.py",
        "autonomous_runtime": "scripts/audit_autonomous_runtime_readiness.py",
        "server_extensions": "scripts/audit_server_extensions_usage.py",
        "repo_safety": "scripts/audit_repo_safety.py",
        "trading_policy": "scripts/audit_trading_decision_policy.py",
        "recovery_unlock": "scripts/assert_recovery_unlock_safety.py",
    }
    for key, script in scripts.items():
        rc, out = _run(script)
        checks[key] = {"rc": rc, "out": out}
        if rc != 0:
            issues.append(f"{key}:{out}")

    live_truth = _read_json(STATE / "live_truth.json", {})
    target_freshness = _read_json(STATE / "target_freshness_audit.json", {})
    ai_usage = _read_json(STATE / "ai_actual_usage_audit.json", {})
    runtime = _read_json(STATE / "autonomous_runtime_readiness_audit.json", {})
    repo_safety = _read_json(STATE / "repo_safety_audit.json", {})
    policy = _read_json(STATE / "trading_decision_policy_audit.json", {})
    no_trade = _read_json(STATE / "no_trade_forensics.json", {})
    recovery = _read_json(STATE / "recovery_reset_plan.json", {})

    recovery_allow_scale_up = (
        bool((recovery.get("policy") or {}).get("allow_scale_up", True))
        if isinstance(recovery.get("policy"), dict)
        else bool(recovery.get("allow_scale_up", True))
    )
    if "allow_scale_up" in recovery and isinstance(recovery.get("allow_scale_up"), bool):
        recovery_allow_scale_up = bool(recovery.get("allow_scale_up"))

    ready = (
        str(live_truth.get("runtime_mode") or "") == "LIVE_ONLY"
        and str(target_freshness.get("status") or "") == "FRESH"
        and str(ai_usage.get("status") or "") in {"USED", "ACTIVE_BUT_NOT_USED"}
        and str(runtime.get("status") or "") in {"READY", "LOCKED_BY_RISK"}
        and str(repo_safety.get("status") or "") in {"SAFE", "WARN_RUNTIME_STATE_COMMITTED"}
        and str(policy.get("status") or "") in {"KEEP", "TIGHTEN"}
        and str(no_trade.get("classification") or "") in {"HEALTHY_WAIT", "HEALTHY_WAIT_LOCKED_BY_RISK"}
        and not recovery_allow_scale_up
    )

    if issues or not ready:
        print(json.dumps({
            "status": "NO",
            "issues": issues,
            "checks": checks,
            "live_truth_risk": live_truth.get("risk_state"),
            "target_freshness": target_freshness.get("status"),
            "ai_usage": ai_usage.get("status"),
            "runtime_readiness": runtime.get("status"),
            "repo_safety": repo_safety.get("status"),
            "policy": policy.get("status"),
            "no_trade": no_trade.get("classification"),
        }, indent=2, ensure_ascii=False))
        print("FINAL:BOLEH_DITINGGAL=NO")
        return 1

    print(json.dumps({
        "status": "YES",
        "checks": checks,
        "live_truth_risk": live_truth.get("risk_state"),
        "target_freshness": target_freshness.get("status"),
        "ai_usage": ai_usage.get("status"),
        "runtime_readiness": runtime.get("status"),
        "repo_safety": repo_safety.get("status"),
        "policy": policy.get("status"),
        "no_trade": no_trade.get("classification"),
    }, indent=2, ensure_ascii=False))
    print("FINAL:BOLEH_DITINGGAL=YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
