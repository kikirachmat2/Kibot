from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "server_telemetry.json"


def _disk_usage_pct(path: str = "/") -> float:
    if psutil is not None:
        try:
            return float(psutil.disk_usage(path).percent)
        except Exception:
            return 0.0
    try:
        total, used, _ = shutil.disk_usage(path)
        return (used / total * 100.0) if total else 0.0
    except Exception:
        return 0.0


def _mem_usage_pct() -> float:
    if psutil is not None:
        try:
            return float(psutil.virtual_memory().percent)
        except Exception:
            return 0.0
    return 0.0


def _cpu_usage_pct() -> float:
    if psutil is not None:
        try:
            raw_cpu = psutil.cpu_percent(interval=None)
            return float(raw_cpu if isinstance(raw_cpu, (int, float)) else 0.0)
        except Exception:
            return 0.0
    return 0.0


def collect_server_telemetry() -> Dict[str, Any]:
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "hostname": os.uname().nodename if hasattr(os, "uname") else "",
        "cpu": round(_cpu_usage_pct(), 2),
        "ram": round(_mem_usage_pct(), 2),
        "disk": round(_disk_usage_pct("/"), 2),
        "loadavg": os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0),
    }


def write_server_telemetry(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data = collect_server_telemetry()
    if payload:
        data.update(payload)
    STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data
