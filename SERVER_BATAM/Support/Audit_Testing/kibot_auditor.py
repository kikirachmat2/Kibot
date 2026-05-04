#!/usr/bin/env python3
"""
KiBot Auditor
=============
Infrastructure-only self-healing and validation.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(os.getenv("KIBOT_RUNTIME_ROOT", Path(__file__).resolve().parent.parent))
STATE_DIR = ROOT / "state"
BACKUP_DIR = STATE_DIR / "backups"
EVENTS_DIR = STATE_DIR / "events"
AUDIT_LOG = STATE_DIR / "audit_log.jsonl"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
EVENTS_DIR.mkdir(parents=True, exist_ok=True)

SAFE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "daily_guard.json": {"hard_stopped": True, "reason": "AUDITOR_RESTORED_CORRUPT_FILE", "daily_pnl_pct": 0.0},
    "manager_gate.json": {"entry_state": "SUSPENDED", "mode": "CONSERVATIVE"},
}
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_runtime_identity() -> Dict[str, str]:
    env_file = ROOT / ".env.kibot"
    values: Dict[str, str] = {}
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                raw = line.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                key, value = raw.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
        except Exception:
            values = {}
    return {
        "exchange_kind": (os.getenv("KIBOT_EXCHANGE_KIND") or values.get("KIBOT_EXCHANGE_KIND") or "").strip().upper(),
        "bot_id": (os.getenv("BOT_ID") or values.get("BOT_ID") or "").strip().lower(),
        "profile_key": (os.getenv("BOT_PROFILE_KEY") or values.get("BOT_PROFILE_KEY") or "").strip().lower(),
    }


def resolve_local_engine_service() -> str:
    identity = load_runtime_identity()
    hint = " ".join([identity["exchange_kind"].lower(), identity["bot_id"], identity["profile_key"]])
    if identity["exchange_kind"] == "INDODAX" or any(token in hint for token in ("indodax", "KiBot", "main")):
        return "kibot-executor-indodax"
    return "kibot-executor-indodax"


SYSTEMD_SERVICES = [
    resolve_local_engine_service(),
    "kibot-manager",
    "kibot-guardian",
    "kibot-analyst",
    "kibot-notifier",
    "kibot-orchestrator",
    "kibot-security",
]


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


def log_audit(action: str, result: str, details: str = "") -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": now_iso(), "action": action, "result": result, "details": details}) + "\n")


def push_event(event_type: str, message: str, severity: str = "INFO") -> None:
    atomic_write(
        EVENTS_DIR / f"{event_type}_{int(time.time() * 1000)}.json",
        {"type": event_type, "ts": now_iso(), "message": message, "severity": severity},
    )


def fix_symlink_conflict(service: str) -> bool:
    symlink_path = Path(f"/etc/systemd/system/multi-user.target.wants/{service}.service")
    if not symlink_path.exists():
        return True
    if symlink_path.is_symlink():
        try:
            target = symlink_path.resolve(strict=True)
            log_audit(f"CHECK_SYMLINK_{service}", "OK", f"Symlink healthy -> {target}")
            return True
        except FileNotFoundError:
            pass
    else:
        log_audit(f"CHECK_SYMLINK_{service}", "SKIPPED", f"Non-symlink path present at {symlink_path}; manual review recommended")
        return True
    try:
        subprocess.run(["sudo", "rm", "-f", str(symlink_path)], check=True, timeout=10)
        subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True, timeout=30)
        log_audit(f"FIX_SYMLINK_{service}", "SUCCESS", f"Removed broken symlink: {symlink_path}")
        push_event("SYMLINK_FIXED", f"Removed broken symlink: {symlink_path}", "INFO")
        return True
    except Exception as error:
        log_audit(f"FIX_SYMLINK_{service}", "FAILED", str(error))
        return False


def fix_all_symlinks() -> int:
    fixed = 0
    for service in SYSTEMD_SERVICES:
        if fix_symlink_conflict(service):
            fixed += 1
    return fixed


def backup_state_files() -> int:
    state_files = [
        STATE_DIR / "daily_guard.json",
        STATE_DIR / "manager_gate.json",
        STATE_DIR / "learning_state.json",
        STATE_DIR / "analyst" / "daily_summary.json",
    ]
    backup_path = BACKUP_DIR / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path.mkdir(parents=True, exist_ok=True)
    backed_up = 0
    for state_file in state_files:
        if state_file.exists():
            shutil.copy2(state_file, backup_path / state_file.name)
            backed_up += 1
    old_dirs = sorted([item for item in BACKUP_DIR.iterdir() if item.is_dir()])
    for old_dir in old_dirs[:-7]:
        shutil.rmtree(old_dir, ignore_errors=True)
    log_audit("BACKUP_STATE", "SUCCESS", f"Backed up {backed_up} files to {backup_path}")
    return backed_up


def _restore_from_backup(filename: str, destination: Path) -> bool:
    for backup_dir in sorted([item for item in BACKUP_DIR.iterdir() if item.is_dir()], reverse=True)[:3]:
        backup_file = backup_dir / filename
        if not backup_file.exists():
            continue
        try:
            json.loads(backup_file.read_text(encoding="utf-8"))
            shutil.copy2(backup_file, destination)
            log_audit(f"RESTORE_BACKUP_{filename}", "SUCCESS", f"Restored from {backup_dir}")
            return True
        except Exception:
            continue
    return False


def verify_and_fix_state_files() -> None:
    for filename, default in SAFE_DEFAULTS.items():
        path = STATE_DIR / filename
        if not path.exists():
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            restored = _restore_from_backup(path.name, path)
            if not restored:
                atomic_write(path, default)
                log_audit(f"RESTORE_DEFAULT_{path.name}", "SUCCESS", "Restored to safe default")
                push_event("STATE_RESTORED", f"State file {path.name} was corrupt, restored to safe default", "WARNING")


def verify_jar_integrity(jar_path: Path) -> bool:
    try:
        with zipfile.ZipFile(jar_path) as archive:
            entries = archive.namelist()
            ok = "META-INF/MANIFEST.MF" in entries and any("MacEngineDaemon" in entry for entry in entries) and len(entries) > 100
            if not ok:
                raise ValueError("missing required classes or manifest")
            return True
    except Exception as error:
        log_audit("JAR_CORRUPT", "DETECTED", f"{jar_path}: {error}")
        push_event("JAR_CORRUPT", f"JAR file corrupt: {jar_path}. Deploy ulang diperlukan.", "CRITICAL")
        return False


def generate_audit_report_for_ai() -> Dict[str, Any]:
    recent_actions: List[Dict[str, Any]] = []
    if AUDIT_LOG.exists():
        for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines()[-50:]:
            try:
                recent_actions.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    guardian_state = {}
    guardian_path = STATE_DIR / "guardian_state.json"
    if guardian_path.exists():
        try:
            guardian_state = json.loads(guardian_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            guardian_state = {}
    daily = {}
    daily_path = STATE_DIR / "analyst" / "daily_summary.json"
    if daily_path.exists():
        try:
            daily = json.loads(daily_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            daily = {}
    return {
        "report_type": "AUDITOR_REPORT",
        "ts": now_iso(),
        "recent_fixes": [item for item in recent_actions if item.get("result") == "SUCCESS"][-10:],
        "recent_failures": [item for item in recent_actions if item.get("result") == "FAILED"][-10:],
        "server_health": guardian_state,
        "trading_performance": daily,
        "question_for_ai": (
            "Apakah ada pola kegagalan infrastruktur berulang dan optimasi aman apa yang cocok untuk Oracle Micro 1GB RAM?"
        ),
    }


def check_peer_connectivity() -> bool:
    try:
        import socket
        identity = load_runtime_identity()
        hint = " ".join([identity["exchange_kind"].lower(), identity["bot_id"], identity["profile_key"]])
        is_indodax = identity["exchange_kind"] == "INDODAX" or any(token in hint for token in ("indodax", "KiBot", "main"))
        peer_host = os.getenv("KiBot_UDP_HOST") if is_indodax else os.getenv("KiBot_UDP_HOST")
        peer_port = 8788 if is_indodax else 8787
        if not peer_host:
            return True
        
        # UDP checking is tricky via connect_ex (TCP only). 
        # For now, we assume if we can reach the peer IP on any standard port (like 22), the link is up.
        # Or we check if the port is bound (hard to do remotely without UDP probe).
        
        # fallback: check common management port if UDP check is ambiguous
        check_port = peer_port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.5)
            result = s.connect_ex((peer_host, 22)) # Check SSH for general host health
            if result == 0:
                log_audit("PEER_HEALTH", "SUCCESS", f"Peer {peer_host} is alive (SSH responsive)")
                return True
            else:
                log_audit("PEER_HEALTH", "FAILED", f"Peer {peer_host} unreachable")
                push_event("PEER_OFFLINE", f"CRITICAL: Peer {peer_host} is totally unreachable (SSH failed).", "CRITICAL")
                return False
    except Exception as e:
        log_audit("PEER_HEARTBEAT_ERROR", "ERROR", str(e))
        return False


def jar_candidates() -> List[Path]:
    candidates = [
        ROOT / "server" / "mac-engine-all.jar",
        Path("/home/ubuntu/KiBot/server/mac-engine-all.jar"),
        Path("/home/ubuntu/KiBot/server/mac-engine-all.jar"),
    ]
    seen = set()
    unique: List[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique

def run_audit_cycle() -> None:
    print("[AUDITOR] Starting audit cycle")
    fix_all_symlinks()
    backup_state_files()
    verify_and_fix_state_files()
    check_peer_connectivity()
    for jar in jar_candidates():
        if jar.exists():
            verify_jar_integrity(jar)
    log_audit("AUDIT_CYCLE", "COMPLETE", f"Cycle done at {now_iso()}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix-symlinks-only", action="store_true")
    args = parser.parse_args()
    if args.fix_symlinks_only:
        fix_all_symlinks()
        return
    while True:
        try:
            run_audit_cycle()
        except Exception as error:
            log_audit("AUDITOR_LOOP", "FAILED", str(error))
        time.sleep(300)


if __name__ == "__main__":
    main()
