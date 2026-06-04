#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
OUT = STATE / "runtime_topology_audit.json"

CORE_SERVICES = {
    "kibot-live-truth",
    "kibot-capital-governor",
    "kibot-scanner",
    "kibot-target-board",
    "kibot-autonomous-brain",
    "kibot-indodax-director",
    "kibot-phantom-brain",
    "kibot-live-dispatcher",
    "kibot-executor",
    "kibot-dashboard",
}

SUPPORT_SERVICES = {
    "kibot-ai-scout",
    "kibot-daily-reset",
    "kibot-janitor",
    "kibot-master",
    "kibot-scanner-health",
    "kibot-telemetry",
    "kibot-workflow-supervisor",
}

OPTIONAL_ROUTE_SERVICES = {
    "kibot-base",
    "kibot-pumpfun",
    "kibot-future-web3",
    "kibot-executor-polymarket",
    "kibot-web3-exit",
}


def _run(args: list[str]) -> str:
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return ""


def _service_state(service: str) -> dict:
    raw = _run(["systemctl", "show", service, "-p", "ActiveState", "-p", "MainPID", "-p", "ExecMainStartTimestamp", "--no-pager"])
    data: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = value
    return {
        "service": service,
        "active_state": data.get("ActiveState", "unknown"),
        "main_pid": int(data.get("MainPID") or 0),
        "start_timestamp": data.get("ExecMainStartTimestamp", ""),
    }


def _category(service: str) -> str:
    if service in CORE_SERVICES:
        return "CORE"
    if service in SUPPORT_SERVICES:
        return "SUPPORT"
    if service in OPTIONAL_ROUTE_SERVICES:
        return "OPTIONAL_ROUTE"
    return "UNKNOWN"


def _running_python_processes() -> list[dict]:
    raw = _run(["ps", "-eo", "pid,lstart,cmd"])
    rows = []
    for line in raw.splitlines()[1:]:
        if "KiBot" not in line and "Core." not in line and "Core/" not in line and "MasterNode.py" not in line:
            continue
        parts = line.split(maxsplit=6)
        if len(parts) < 7:
            continue
        rows.append(
            {
                "pid": int(parts[0]),
                "started": " ".join(parts[1:6]),
                "cmd": parts[6],
                "managed_by_systemd": "/home/ubuntu/KiBot/.venv/" in parts[6]
                or "cloudflared" in parts[6]
                or "uvicorn" in parts[6],
            }
        )
    return rows


def main() -> None:
    services = sorted(CORE_SERVICES | SUPPORT_SERVICES | OPTIONAL_ROUTE_SERVICES)
    service_rows = []
    for svc in services:
        row = _service_state(svc)
        row["category"] = _category(svc)
        service_rows.append(row)

    processes = _running_python_processes()
    unmanaged = [
        p
        for p in processes
        if not p["managed_by_systemd"]
        and "fail2ban" not in p["cmd"]
        and "cloudflared" not in p["cmd"]
    ]
    inactive_core = [s for s in service_rows if s["category"] == "CORE" and s["active_state"] != "active"]
    noisy_optional = []
    for svc in sorted(OPTIONAL_ROUTE_SERVICES):
        recent = _run(["journalctl", "-u", svc, "--since", "10 minutes ago", "--no-pager"])
        error_count = sum(1 for line in recent.splitlines() if any(token in line.lower() for token in ("error", "traceback", "exception", "failed")))
        if error_count:
            noisy_optional.append({"service": svc, "error_lines_10m": error_count})

    status = "OK"
    if unmanaged or inactive_core:
        status = "NEEDS_CLEANUP"
    elif noisy_optional:
        status = "OPTIONAL_NOISE"

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "core_services": [s for s in service_rows if s["category"] == "CORE"],
        "support_services": [s for s in service_rows if s["category"] == "SUPPORT"],
        "optional_route_services": [s for s in service_rows if s["category"] == "OPTIONAL_ROUTE"],
        "unmanaged_kibot_processes": unmanaged,
        "inactive_core_services": inactive_core,
        "noisy_optional_services": noisy_optional,
        "recommendation": (
            "keep core, keep support if quiet, lock or disable optional route services when they emit repeated errors"
            if status != "OK"
            else "runtime topology clean"
        ),
    }
    STATE.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"OK:RUNTIME_TOPOLOGY_AUDITED status={status}")
    if unmanaged:
        print(f"unmanaged_kibot_processes={len(unmanaged)}")
    if noisy_optional:
        print(f"noisy_optional_services={noisy_optional}")


if __name__ == "__main__":
    main()
