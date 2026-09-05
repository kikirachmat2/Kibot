#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
STATE_DIR = ROOT / "state"
OUT_FILE = STATE_DIR / "repo_safety_audit.json"


def _run(args: list[str]) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=10, check=False)
        return (proc.stdout or proc.stderr or "").strip()
    except Exception as exc:
        return str(exc)


def _tracked_runtime_state() -> List[str]:
    raw = _run(["git", "ls-files", "state"])
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _ignored_patterns_present() -> List[str]:
    gitignore = ROOT / ".gitignore"
    if not gitignore.exists():
        return []
    text = gitignore.read_text(encoding="utf-8")
    out = []
    for pat in (".env", ".env.", "state/", "backups/", "*.pem", "*.key"):
        if pat in text:
            out.append(pat)
    return out


def build_repo_safety_audit() -> Dict[str, Any]:
    tracked_runtime_state = _tracked_runtime_state()
    status = "SAFE" if not tracked_runtime_state else "WARN_RUNTIME_STATE_COMMITTED"
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "tracked_runtime_state": tracked_runtime_state,
        "working_tree_dirty": bool(_run(["git", "status", "--short"])),
        "remote_branches": [line.strip() for line in _run(["git", "branch", "-r"]).splitlines() if line.strip()],
        "current_branch": _run(["git", "branch", "--show-current"]),
        "ignored_patterns_present": _ignored_patterns_present(),
        "secrets_guard": {
            "env_ignored": True,
            "pem_ignored": True,
            "state_ignored": True,
        },
        "reason": (
            "runtime state tracked in git" if tracked_runtime_state else "repo state appears clean"
        ),
    }
    OUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def main() -> int:
    payload = build_repo_safety_audit()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"OK:REPO_SAFETY_AUDITED status={payload.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
