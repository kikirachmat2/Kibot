from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "server_telemetry.json"


def _gb(v: float) -> float:
    return round(v / (1024 ** 3), 3)


def _service_state(name: str) -> Dict[str, Any]:
    try:
        active = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=6).stdout.strip()
    except Exception as exc:
        active = f"error:{exc}"
    try:
        enabled = subprocess.run(["systemctl", "is-enabled", name], capture_output=True, text=True, timeout=6).stdout.strip()
    except Exception as exc:
        enabled = f"error:{exc}"
    return {"active": active, "enabled": enabled}


def _top_processes(limit: int = 5) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if psutil is None:
        return out
    try:
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "cmdline"]):
            try:
                info = getattr(p, "info", {}) if hasattr(p, "info") else {}
                if not info or not info.get("name"):
                    continue
                procs.append({
                    "pid": info.get("pid"),
                    "name": info.get("name"),
                    "cpu_percent": float(info.get("cpu_percent") or 0.0),
                    "memory_percent": float(info.get("memory_percent") or 0.0),
                    "cmdline": " ".join(info.get("cmdline") or [])[:120],
                })
            except Exception:
                continue
        procs.sort(key=lambda x: (x["cpu_percent"], x["memory_percent"]), reverse=True)
        return procs[:limit]
    except Exception:
        return out


def collect_server_telemetry() -> Dict[str, Any]:
    if psutil is not None:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        raw_cpu = psutil.cpu_percent(interval=None)
        cpu = float(raw_cpu if isinstance(raw_cpu, (int, float)) else 0.0)
        load_1m, load_5m, load_15m = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
        uptime = max(0.0, datetime.now(timezone.utc).timestamp() - psutil.boot_time())
        total_proc = len(psutil.pids())
    else:
        total, used, free = shutil.disk_usage("/")
        mem_total = mem_used = mem_avail = 0
        cpu = 0.0
        load_1m, load_5m, load_15m = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
        uptime = 0.0
        total_proc = 0
        mem = type("Mem", (), {"total": mem_total, "used": mem_used, "available": mem_avail, "percent": 0.0})()
        disk = type("Disk", (), {"total": total, "used": used, "free": free, "percent": (used / total * 100.0) if total else 0.0})()

    services = {name: _service_state(name) for name in [
        "kibot-capital-governor", "kibot-indodax-director", "kibot-scanner", "kibot-scanner-health",
        "kibot-executor", "kibot-ai-scout", "kibot-dashboard", "kibot-cloudflared", "redis-server", "ollama"
    ]}
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cpu": {"percent": round(float(cpu or 0.0), 2), "load_1m": round(load_1m, 3), "load_5m": round(load_5m, 3), "load_15m": round(load_15m, 3)},
        "ram": {"total_gb": _gb(float(getattr(mem, "total", 0.0) or 0.0)), "used_gb": _gb(float(getattr(mem, "used", 0.0) or 0.0)), "available_gb": _gb(float(getattr(mem, "available", 0.0) or 0.0)), "percent": round(float(getattr(mem, "percent", 0.0) or 0.0), 2)},
        "disk": {"total_gb": _gb(float(getattr(disk, "total", 0.0) or 0.0)), "used_gb": _gb(float(getattr(disk, "used", 0.0) or 0.0)), "free_gb": _gb(float(getattr(disk, "free", 0.0) or 0.0)), "percent": round(float(getattr(disk, "percent", 0.0) or 0.0), 2)},
        "uptime_seconds": int(uptime),
        "process_count": int(total_proc),
        "services": services,
        "top_processes": _top_processes(),
    }


def write_server_telemetry(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data = collect_server_telemetry()
    if payload:
        data.update(payload)
    STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data
