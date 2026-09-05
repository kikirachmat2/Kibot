#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Support.ki_config import STATE_DIR

OUT_FILE = STATE_DIR / "server_extensions_usage_audit.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, (dict, list)) else default
    except Exception:
        return default
    return default


def _service_active(name: str) -> bool:
    try:
        proc = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=5, check=False)
        return str(proc.stdout).strip() == "active"
    except Exception:
        return False


def build_server_extensions_usage_audit() -> Dict[str, Any]:
    telemetry = _read_json(STATE_DIR / "server_telemetry.json", {})
    inventory = _read_json(STATE_DIR / "ai_system_inventory.json", {})
    tools = {
        "gh": bool(shutil.which("gh")),
        "copilot": bool(shutil.which("copilot")) or bool(shutil.which("gh")),
        "aider": bool(shutil.which("aider")) or bool((Path.home() / ".local/bin/aider").exists()),
        "crush": bool(shutil.which("crush")),
        "ollama": _service_active("ollama"),
        "redis": _service_active("redis-server"),
        "cloudflared": _service_active("kibot-cloudflared"),
    }
    runtime_services = {
        name: _service_active(name)
        for name in (
            "kibot-live-truth",
            "kibot-master",
            "kibot-scanner",
            "kibot-executor",
            "kibot-dashboard",
            "kibot-workflow-supervisor",
            "kibot-ai-scout",
            "kibot-telemetry",
        )
    }
    extension_usage = {
        "telemetry_writes": bool(telemetry.get("updated_at")),
        "dashboard_reads_control_plane": bool((inventory.get("state_snapshots") or {}).get("live_truth.json")),
        "copilot_available": tools["copilot"],
        "gh_available": tools["gh"],
        "aider_available": tools["aider"],
        "crush_available": tools["crush"],
        "ollama_active": tools["ollama"],
        "redis_active": tools["redis"],
        "cloudflared_active": tools["cloudflared"],
        "systemd_source_of_truth": True,
    }
    used_count = sum(1 for value in extension_usage.values() if bool(value))
    status = "USED" if used_count >= 6 and runtime_services["kibot-dashboard"] and runtime_services["kibot-live-truth"] else "ACTIVE_BUT_NOT_USED" if any(runtime_services.values()) else "BROKEN"
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "tools": tools,
        "runtime_services": runtime_services,
        "extension_usage": extension_usage,
        "used_count": used_count,
        "unused_but_active": [name for name, active in tools.items() if active and not extension_usage.get(f"{name}_active", False) and name not in {"gh", "copilot"}],
        "evidence": {
            "telemetry": telemetry,
            "ai_inventory": inventory,
        },
    }
    OUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def main() -> int:
    payload = build_server_extensions_usage_audit()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"OK:SERVER_EXTENSIONS_USAGE_AUDITED status={payload.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
