#!/usr/bin/env python3
"""
KiBot Server Guardian
=====================
Infrastructure watchdog for Oracle Micro.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - runtime fallback
    psutil = None

ROOT = Path(os.getenv("KIBOT_RUNTIME_ROOT", Path(__file__).resolve().parent.parent))
STATE_DIR = ROOT / "state"
EVENTS_DIR = STATE_DIR / "events"
LOGS_DIR = ROOT / "logs"
GUARDIAN_STATE = STATE_DIR / "guardian_state.json"

RAM_WARN_PCT = 80
RAM_CRITICAL_PCT = 90
DISK_WARN_PCT = 75
DISK_CRITICAL_PCT = 90
CPU_WARN_PCT = 90
CPU_WARN_SUSTAINED_S = 300
MAX_SERVICE_RESTARTS_PER_HOUR = 3
HEURISTIC_FALLBACK_WARN_SEC = int(os.getenv("KIBOT_GUARDIAN_HEURISTIC_WARN_SEC", "900"))
HEURISTIC_FALLBACK_RESTART_SEC = int(os.getenv("KIBOT_GUARDIAN_HEURISTIC_RESTART_SEC", "1800"))
restart_counts: Dict[str, List[float]] = {}
health_issue_since: Dict[str, float] = {}
ENGINE_DEGRADED_RESTART_SEC = int(os.getenv("KIBOT_GUARDIAN_ENGINE_DEGRADED_RESTART_SEC", "600"))
MANAGER_SUSPEND_RESTART_SEC = int(os.getenv("KIBOT_GUARDIAN_MANAGER_SUSPEND_RESTART_SEC", "600"))
BUG_DETECTOR_ENABLED = os.getenv("KIBOT_GUARDIAN_BUG_DETECTOR", "true").lower() == "true"
ERROR_PATTERNS = [
    r"NameError:",
    r"KeyError:",
    r"AttributeError:",
    r"ImportError:",
    r"RecursionError:",
    r"ModuleNotFoundError:",
    r"SyntaxError:",
    r"IndexError:",
]
SERVICE_HEALTH_URLS = {
    "kibot-executor-indodax": f"http://{os.getenv('KIBOT_EXECUTOR_IP', '213.35.118.26')}:8787/api/health",
    "kibot-polymarket": f"http://{os.getenv('KIBOT_EXECUTOR_IP', '213.35.118.26')}:11600/health",
    "kibot-manager": "http://127.0.0.1:9998/api/state",
    "kibot-ollama-gateway": "http://127.0.0.1:11435/health",
}


def _parse_guardian_service_override(raw: str) -> List[str]:
    return [
        token.strip()
        for token in raw.split(",")
        if token.strip()
    ]


def _load_runtime_identity_from_env_file() -> Dict[str, str]:
    env_file = ROOT / ".env.kibot"
    values: Dict[str, str] = {}
    if not env_file.exists():
        return values
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        return {}
    return values


def resolve_services_to_guard() -> List[str]:
    """
    Resolves the list of services to guard based on node identity.
    Authority: ROLE_MANIFEST.md
    """
    override = os.getenv("KIBOT_GUARDIAN_SERVICES", "").strip()
    if override:
        return [s.strip() for s in override.split(",") if s.strip()]

    file_identity = _load_runtime_identity_from_env_file()
    # Priority: Env Var > .env.kibot > hostname heuristic
    role = (os.getenv("KIBOT_ROLE") or file_identity.get("KIBOT_ROLE") or "").strip().upper()
    hostname = socket.gethostname().lower()

    if not role:
        if "batam" in hostname or "brain" in hostname: role = "BATAM"
        elif "executor" in hostname: role = "EXECUTOR"
        elif "scanner" in hostname: role = "SCANNER"

    if role == "BATAM":
        return [
            "kibot-manager", "kibot-analyst", "kibot-auditor", "kibot-notifier",
            "kibot-orchestrator", "kibot-security", "kibot-ollama-gateway",
            "ki-telegram-monitor", "indodax-dashboard-proxy", "lazarus-ampere"
        ]
    elif role == "EXECUTOR":
        return ["kibot-executor-indodax", "kibot-polymarket"]
    elif role == "SCANNER":
        return ["ki-global-scanner-mesh"]
    
    # Fallback to a minimal safe set if role is unknown
    return ["kibot-manager"]


SERVICES_TO_GUARD = resolve_services_to_guard()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def push_event(event_type: str, message: str, severity: str = "WARNING", data: Optional[Dict[str, Any]] = None) -> None:
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"type": event_type, "ts": now_iso(), "message": message, "severity": severity, "data": data or {}}
    atomic_write(EVENTS_DIR / f"{event_type}_{int(time.time() * 1000)}.json", payload)


def _fallback_memory_snapshot() -> Dict[str, Any]:
    try:
        output = subprocess.check_output(["/usr/bin/env", "sh", "-c", "free -m | awk 'NR==2 {print $2\" \"$3\" \"$7}'"], text=True).strip()
        total_mb, used_mb, available_mb = [int(part) for part in output.split()]
        used_pct = round((used_mb / max(total_mb, 1)) * 100, 1)
        return {"percent": used_pct, "available_mb": available_mb, "swap_used_mb": 0}
    except Exception:
        return {"percent": 0.0, "available_mb": 0, "swap_used_mb": 0}


def check_memory() -> Dict[str, Any]:
    if psutil is None:
        mem_info = _fallback_memory_snapshot()
        ram_pct = mem_info["percent"]
        available_mb = mem_info["available_mb"]
        swap_used_mb = mem_info["swap_used_mb"]
    else:
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        ram_pct = float(mem.percent)
        available_mb = int(mem.available // 1_000_000)
        swap_used_mb = int(swap.used // 1_000_000)
    result = {"ram_pct": ram_pct, "ram_available_mb": available_mb, "swap_used_mb": swap_used_mb, "status": "OK"}
    if ram_pct >= RAM_CRITICAL_PCT:
        result["status"] = "CRITICAL"
        push_event("RAM_CRITICAL", f"RAM {ram_pct:.0f}% — killing non-critical processes", "CRITICAL", result)
        _kill_non_critical_processes()
    elif ram_pct >= RAM_WARN_PCT:
        result["status"] = "WARNING"
        push_event("RAM_WARNING", f"RAM {ram_pct:.0f}% (available: {available_mb}MB)", "WARNING", result)
    if swap_used_mb > 200:
        push_event("SWAP_HIGH", f"Swap {swap_used_mb}MB — RAM sangat terbatas", "WARNING", {"swap_mb": swap_used_mb})
    return result


def check_disk() -> Dict[str, Any]:
    usage = shutil.disk_usage(str(ROOT))
    used_pct = round((usage.used / max(usage.total, 1)) * 100, 1)
    result = {"used_pct": used_pct, "free_gb": round(usage.free / 1_000_000_000, 2), "status": "OK"}
    if used_pct >= DISK_CRITICAL_PCT:
        result["status"] = "CRITICAL"
        push_event("DISK_CRITICAL", f"Disk {used_pct:.0f}% — auto cleanup dimulai", "CRITICAL", result)
        _auto_cleanup_disk()
    elif used_pct >= DISK_WARN_PCT:
        result["status"] = "WARNING"
        push_event("DISK_WARNING", f"Disk {used_pct:.0f}% (free: {result['free_gb']:.1f}GB)", "WARNING", result)
    return result


def check_services() -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    for service in SERVICES_TO_GUARD:
        try:
            load_state = subprocess.run(
                ["systemctl", "show", service, "--property=LoadState", "--value"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            if load_state == "not-found":
                results[service] = {"active": False, "installed": False, "status": "not_found"}
                continue
            proc = subprocess.run(["systemctl", "is-active", service], capture_output=True, text=True, timeout=5)
            is_active = proc.stdout.strip() == "active"
            results[service] = {"active": is_active, "installed": True, "status": proc.stdout.strip()}
            if not is_active:
                health_issue_since.pop(service, None)
                _restart_service(service, reason="inactive", action="start")
                continue
            health = _check_service_health(service)
            results[service].update(health)
            if health.get("healthy", True):
                health_issue_since.pop(service, None)
                _check_for_bugs(service)
                continue
            since = health_issue_since.setdefault(service, time.time())
            unhealthy_for = time.time() - since
            results[service]["unhealthy_for_sec"] = round(unhealthy_for, 1)
            threshold = _restart_threshold_for(service, health)
            if threshold > 0 and unhealthy_for >= threshold:
                _restart_service(
                    service,
                    reason=str(health.get("reason") or "unhealthy"),
                    action="restart",
                )
                health_issue_since.pop(service, None)
        except Exception as error:
            results[service] = {"active": False, "error": str(error)}
    return results


def _restart_threshold_for(service: str, health: Dict[str, Any]) -> int:
    if service in {"kibot-executor-indodax", "kibot-executor-indodax"}:
        return ENGINE_DEGRADED_RESTART_SEC
    if service == "kibot-manager":
        reason = str(health.get("reason") or "")
        if "math_review_recovery_impossible" in reason or "state_unhealthy" in reason or "manager_http_error" in reason:
            return MANAGER_SUSPEND_RESTART_SEC
    return 0


def _load_health_payload(url: str) -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = ""
        try:
            body = error.read().decode("utf-8")
        except Exception:
            body = ""
        if body:
            try:
                return json.loads(body)
            except Exception:
                pass
        raise


def _check_service_health(service: str) -> Dict[str, Any]:
    url = SERVICE_HEALTH_URLS.get(service)
    if not url:
        return {"healthy": True, "reason": "no_health_endpoint"}
    try:
        payload = _load_health_payload(url)
    except Exception as error:
        return {"healthy": False, "reason": f"{service}_http_error:{type(error).__name__}"}

    if service in {"kibot-executor-indodax", "kibot-executor-indodax"}:
        effective_state = str(payload.get("effectiveState") or "")
        sync_health = str(payload.get("syncHealth") or "")
        hard_stop_active = bool(payload.get("hardStopActive"))
        if hard_stop_active:
            return {"healthy": True, "reason": "hard_stop_active", "effective_state": effective_state, "sync_health": sync_health}
        if effective_state == "RUNNING" and sync_health == "HEALTHY":
            return {"healthy": True, "reason": "engine_healthy", "effective_state": effective_state, "sync_health": sync_health}
        return {
            "healthy": False,
            "reason": f"engine_degraded:{effective_state}:{sync_health}",
            "effective_state": effective_state,
            "sync_health": sync_health,
        }

    if service == "kibot-manager":
        system_state = str(payload.get("system_state") or payload.get("systemState") or "")
        degraded_reason = str(payload.get("degradedReason") or payload.get("healthDecision") or "")
        hard_stop_active = bool(payload.get("hard_stop_active") or payload.get("hardStopActive"))
        if hard_stop_active:
            return {"healthy": True, "reason": "manager_hard_stop_active", "system_state": system_state}
        if system_state in {"", "HEALTHY"}:
            return {"healthy": True, "reason": "manager_healthy", "system_state": system_state}
        if system_state == "SUSPENDED" and degraded_reason == "math_review_recovery_impossible":
            return {"healthy": False, "reason": "math_review_recovery_impossible", "system_state": system_state}
        return {"healthy": False, "reason": f"manager_state_unhealthy:{system_state}:{degraded_reason}", "system_state": system_state}

    if service == "kibot-ollama-gateway":
        if bool(payload.get("ok")):
            return {"healthy": True, "reason": "gateway_healthy"}
        return {"healthy": False, "reason": "gateway_unhealthy"}

    if service == "kibot-polymarket":
        if bool(payload.get("ready")) and bool(payload.get("analysis_ready", True)):
            return {"healthy": True, "reason": "polymarket_ready"}
        return {
            "healthy": False,
            "reason": "polymarket_not_ready",
            "ready": bool(payload.get("ready")),
            "analysis_ready": bool(payload.get("analysis_ready")),
        }

    return {"healthy": True, "reason": "unsupported_service"}


def _check_for_bugs(service: str) -> None:
    if not BUG_DETECTOR_ENABLED:
        return
    try:
        # Quick journalctl check for critical patterns in last 5 min
        proc = subprocess.run(
            ["journalctl", "-u", service, "--since", "5 min ago", "--no-pager"],
            capture_output=True, text=True, timeout=5
        )
        output = proc.stdout
        for pattern in ERROR_PATTERNS:
            if re.search(pattern, output):
                push_event(
                    "BUG_DETECTED",
                    f"Detected {pattern} in {service} logs!",
                    "CRITICAL",
                    {"service": service, "pattern": pattern}
                )
                # If we see a NameError, it's a code bug. 
                # We restart once, but if it persists, the crash loop protection in _restart_service will kick in.
                _restart_service(service, reason=f"bug_detected:{pattern}", action="restart")
                break
    except Exception:
        pass


def _restart_service(service: str, *, reason: str, action: str) -> None:
    now = time.time()
    recent = [timestamp for timestamp in restart_counts.get(service, []) if now - timestamp < 3600]
    restart_counts[service] = recent
    if len(recent) >= MAX_SERVICE_RESTARTS_PER_HOUR:
        push_event("SERVICE_CRASH_LOOP", f"{service} {len(recent)}x dalam 1 jam", "CRITICAL")
        return

    # Determine if remote
    node = "LOCAL"
    if service in {"kibot-executor-indodax", "kibot-polymarket"}: node = "EXECUTOR"
    
    if node == "LOCAL":
        result = subprocess.run(["sudo", "systemctl", action, service], capture_output=True, text=True, timeout=30)
        success = result.returncode == 0
    else:
        # Remote restart via ki_cluster_ctl.py
        ctl_path = "/home/ubuntu/KiBot/Shared/Ops/ki_cluster_ctl.py"
        cmd = f"sudo systemctl {action} {service}"
        res = subprocess.run(["python3", ctl_path, node, cmd], capture_output=True, text=True, timeout=40)
        success = res.returncode == 0

    restart_counts.setdefault(service, []).append(now)
    push_event("SERVICE_RESTARTED", f"{service} {action}ed on {node}", "WARNING" if success else "CRITICAL")


def _kill_non_critical_processes() -> None:
    for pattern in ["python3.*test_", "python3.*kibot_optimizer"]:
        try:
            subprocess.run(["pkill", "-f", pattern], check=False, capture_output=True)
        except Exception:
            pass


def _auto_cleanup_disk() -> None:
    # Use find with explicit arguments instead of shell strings
    try:
        subprocess.run(["find", str(LOGS_DIR), "-type", "f", "-mtime", "+7", "-delete"], check=False)
        subprocess.run(["find", str(STATE_DIR), "-name", "*.tmp.*", "-delete"], check=False)
        # Note: Complex find with -exec is safer as multiple calls or using a script if needed, 
        # but here we can just target the files and compress them via python if we wanted.
        # For now, just deleting tmp files is the most critical.
    except Exception:
        pass


def check_network() -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    targets = {
        "indodax": "https://indodax.com/api/pairs",
        "binance": "https://api.binance.com/api/v3/ping",
        "supabase": os.getenv("SUPABASE_URL", "").rstrip("/") + "/rest/v1/" if os.getenv("SUPABASE_URL") else "",
    }
    for name, url in targets.items():
        if not url:
            results[name] = {"ok": False, "error": "not_configured"}
            continue
        start = time.time()
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                latency_ms = int((time.time() - start) * 1000)
                results[name] = {"ok": response.status == 200, "latency_ms": latency_ms}
        except urllib.error.HTTPError as error:
            latency_ms = int((time.time() - start) * 1000)
            status = int(getattr(error, "code", 0) or 0)
            ok = 200 <= status < 500
            results[name] = {"ok": ok, "latency_ms": latency_ms, "http_status": status}
            if not ok:
                push_event(f"NETWORK_{name.upper()}_DOWN", f"Koneksi ke {name} gagal: HTTP {status}", "WARNING", {"target": name, "status": status})
        except Exception as error:
            results[name] = {"ok": False, "error": str(error)[:100]}
            push_event(f"NETWORK_{name.upper()}_DOWN", f"Koneksi ke {name} gagal: {str(error)[:100]}", "WARNING", {"target": name})
    return results


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def check_brain_control() -> Dict[str, Any]:
    directives = _load_json(STATE_DIR / "governor_directives.json")
    governor_state = _load_json(STATE_DIR / "governor_state.json")
    result: Dict[str, Any] = {
        "status": "UNKNOWN",
        "provider": str(directives.get("provider") or governor_state.get("last_provider") or ""),
        "plan_state": str(directives.get("plan_state") or governor_state.get("last_plan_state") or ""),
        "last_refresh_at": str(governor_state.get("last_refresh_at") or ""),
    }
    if not directives and not governor_state:
        result["status"] = "NOT_AVAILABLE"
        return result
    age_sec = 0.0
    if result["last_refresh_at"]:
        try:
            age_sec = max(
                0.0,
                time.time() - datetime.fromisoformat(result["last_refresh_at"].replace("Z", "+00:00")).timestamp(),
            )
        except Exception:
            age_sec = 0.0
    result["age_sec"] = round(age_sec, 1)
    provider = str(result.get("provider") or "").lower()
    if str(result.get("plan_state") or "").upper() == "ACTIVE":
        result["status"] = "OK"
    else:
        result["status"] = "WARNING"
    if provider in {"heuristic", "local-fallback"}:
        result["status"] = "WARNING"
        if age_sec >= HEURISTIC_FALLBACK_WARN_SEC:
            push_event(
                "AI_FALLBACK_ACTIVE",
                f"Governor fallback {provider} aktif selama {int(age_sec)}s",
                "WARNING",
                {"provider": provider, "age_sec": age_sec},
            )
        if age_sec >= HEURISTIC_FALLBACK_RESTART_SEC:
            if "kibot-ollama-tunnel" in SERVICES_TO_GUARD:
                _restart_service("kibot-ollama-tunnel", reason="heuristic_fallback_stuck", action="restart")
            elif "kibot-ollama-gateway" in SERVICES_TO_GUARD:
                _restart_service("kibot-ollama-gateway", reason="heuristic_fallback_stuck", action="restart")
            result["status"] = "CRITICAL"
    if str(result.get("plan_state") or "").upper() == "EXPIRED":
        result["status"] = "CRITICAL"
        push_event(
            "GOVERNOR_PLAN_EXPIRED",
            "Governor plan expired; control plane may be stale",
            "CRITICAL",
            {"provider": provider, "age_sec": age_sec},
        )
    return result


def save_state(metrics: Dict[str, Any]) -> None:
    atomic_write(GUARDIAN_STATE, {"ts": now_iso(), **metrics})


def _systemd_notify(*args: str) -> None:
    notify_socket = os.getenv("NOTIFY_SOCKET")
    if not notify_socket:
        return
    try:
        address: str | bytes = notify_socket
        if notify_socket.startswith("@"):
            address = "\0" + notify_socket[1:]
        payload = "\n".join(args).encode("utf-8")
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(payload)
    except Exception:
        return


def _notify_ready() -> None:
    _systemd_notify("READY=1", f"STATUS=Guardian active: {', '.join(SERVICES_TO_GUARD)}")


def _notify_watchdog(metrics: Dict[str, Any]) -> None:
    memory = metrics.get("memory") if isinstance(metrics.get("memory"), dict) else {}
    disk = metrics.get("disk") if isinstance(metrics.get("disk"), dict) else {}
    services = metrics.get("services") if isinstance(metrics.get("services"), dict) else {}
    service_status = ",".join(
        f"{name}:{'up' if isinstance(data, dict) and data.get('active') else 'down'}"
        for name, data in services.items()
    )
    status = (
        f"ram={memory.get('ram_pct', 0)}% "
        f"disk={disk.get('used_pct', 0)}% "
        f"services={service_status}"
    )
    _systemd_notify(f"STATUS={status}", "WATCHDOG=1")


def run_guardian_loop() -> None:
    print(f"[GUARDIAN] KiBot Server Guardian started. Guarding services: {', '.join(SERVICES_TO_GUARD)}")
    _notify_ready()
    cpu_high_since: Optional[float] = None
    while True:
        try:
            metrics = {
                "memory": check_memory(),
                "disk": check_disk(),
                "services": check_services(),
                "network": check_network(),
                "brain_control": check_brain_control(),
            }
            cpu_pct = float(psutil.cpu_percent(interval=5) if psutil else 0.0)
            metrics["cpu_pct"] = cpu_pct
            if cpu_pct >= CPU_WARN_PCT:
                if cpu_high_since is None:
                    cpu_high_since = time.time()
                elif time.time() - cpu_high_since >= CPU_WARN_SUSTAINED_S:
                    push_event("CPU_SUSTAINED_HIGH", f"CPU {cpu_pct:.0f}% sustained {CPU_WARN_SUSTAINED_S}s", "WARNING", {"cpu_pct": cpu_pct})
                    cpu_high_since = None
            else:
                cpu_high_since = None
            save_state(metrics)
            _notify_watchdog(metrics)
            time.sleep(60)
        except Exception as error:
            push_event("GUARDIAN_LOOP_ERROR", str(error), "WARNING")
            time.sleep(30)


if __name__ == "__main__":
    run_guardian_loop()
