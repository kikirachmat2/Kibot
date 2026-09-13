from __future__ import annotations

import subprocess

from tests._script_loader import load_script_module


def test_repo_safety_warns_on_runtime_state(monkeypatch):
    mod = load_script_module("scripts/audit_repo_safety.py", "audit_repo_safety")

    def fake_run(args, capture_output=True, text=True, timeout=10, check=False):
        cmd = " ".join(args)
        if args[:3] == ["git", "ls-files", "state"]:
            return subprocess.CompletedProcess(args, 0, stdout="state/recovery_reset_plan.json\n", stderr="")
        if args[:3] == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(args, 0, stdout="main\n", stderr="")
        if args[:3] == ["git", "branch", "-r"]:
            return subprocess.CompletedProcess(args, 0, stdout="origin/main\n", stderr="")
        if args[:3] == ["git", "status", "--short"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    payload = mod.build_repo_safety_audit()
    assert payload["status"] == "WARN_RUNTIME_STATE_COMMITTED"
    assert "state/recovery_reset_plan.json" in payload["tracked_runtime_state"]

