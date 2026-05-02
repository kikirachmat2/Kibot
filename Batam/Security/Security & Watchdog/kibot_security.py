#!/usr/bin/env python3
"""
KiBot Security
==============
Security scanner for permissions and secret leaks.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List

ROOT = Path(os.getenv("KIBOT_RUNTIME_ROOT", Path(__file__).resolve().parent.parent))
STATE_DIR = ROOT / "state"
EVENTS_DIR = STATE_DIR / "events"
SECURITY_LOG = STATE_DIR / "security_log.jsonl"

SENSITIVE_FILES = [
    Path("/opt/kibot/.env"),
    ROOT / ".env",
    ROOT / ".env.kibot",
    STATE_DIR / "daily_guard.json",
    STATE_DIR / "manager_gate.json",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_log(record: dict) -> None:
    SECURITY_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(SECURITY_LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _push_event(secret_files: List[str]) -> None:
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = EVENTS_DIR / f"SECURITY_SECRETS_FOUND_{int(time.time() * 1000)}.json"
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    payload = {
        "type": "SECURITY_SECRETS_FOUND",
        "ts": now_iso(),
        "message": f"Potential credentials found in files: {secret_files}",
        "severity": "CRITICAL",
    }
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def check_file_permissions() -> List[str]:
    issues: List[str] = []
    for file_path in SENSITIVE_FILES:
        if not file_path.exists():
            continue
        mode = file_path.stat().st_mode
        if mode & 0o004:
            try:
                file_path.chmod(0o600)
                issues.append(f"{file_path} is world-readable (fixed to 600)")
            except Exception as error:
                issues.append(f"{file_path} is world-readable (fix failed: {error})")
    return issues


def check_git_secrets() -> List[str]:
    dangerous_patterns = [
        "postgresql://",
        "api_key",
        "supabase_anon_key",
        "telegram_bot_token = \"",
        "authorization: bearer",
        "xoxb-",
    ]
    secret_files: List[str] = []
    for file_path in ROOT.rglob("*"):
        if file_path.is_dir():
            continue
        if any(part.startswith(".git") or part in {"build", ".gradle", ".gradle_home", "node_modules", ".venv"} for part in file_path.parts):
            continue
        if file_path.suffix.lower() not in {".md", ".py", ".kt", ".kts", ".yml", ".yaml", ".env", ".txt"}:
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:
            continue
        if "example" in str(file_path).lower():
            continue
        if any(pattern in content for pattern in dangerous_patterns):
            secret_files.append(str(file_path.relative_to(ROOT)))
    return secret_files


def run_security_scan() -> List[str]:
    issues = check_file_permissions()
    secret_files = check_git_secrets()
    all_issues = issues + [f"Potential secrets in: {path}" for path in secret_files]
    if all_issues:
        _append_log({"ts": now_iso(), "issues": all_issues})
        if secret_files:
            _push_event(secret_files)
    return all_issues


if __name__ == "__main__":
    while True:
        run_security_scan()
        time.sleep(3600)
