from __future__ import annotations

import json
import subprocess

from tests._script_loader import load_script_module


def test_assert_boleh_ditinggal_yes(tmp_path, monkeypatch, capsys):
    mod = load_script_module("scripts/assert_boleh_ditinggal.py", "assert_boleh_ditinggal")
    monkeypatch.setattr(mod, "STATE", tmp_path)

    state_files = {
        "live_truth.json": {"runtime_mode": "LIVE_ONLY", "risk_state": "OK"},
        "target_freshness_audit.json": {"status": "FRESH"},
        "ai_actual_usage_audit.json": {"status": "USED"},
        "autonomous_runtime_readiness_audit.json": {"status": "READY"},
        "server_extensions_usage_audit.json": {"status": "USED"},
        "repo_safety_audit.json": {"status": "SAFE"},
        "trading_decision_policy_audit.json": {"status": "TIGHTEN"},
        "no_trade_forensics.json": {"classification": "HEALTHY_WAIT"},
        "recovery_reset_plan.json": {"policy": {"allow_scale_up": False}},
    }
    for name, payload in state_files.items():
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")

    def fake_run(args, capture_output=True, text=True, check=False):
        script = str(args[-1])
        if "assert_live_truth_writer.py" in script:
            return subprocess.CompletedProcess(args, 0, stdout="OK:LIVE_TRUTH_FRESH age=1.0s risk=OK\n", stderr="")
        if "assert_dashboard_live_truth.py" in script:
            return subprocess.CompletedProcess(args, 0, stdout="OK:DASHBOARD_LIVE_TRUTH\n", stderr="")
        if "audit_target_freshness.py" in script:
            return subprocess.CompletedProcess(args, 0, stdout="OK:TARGET_FRESHNESS_AUDITED status=FRESH\n", stderr="")
        if "audit_ai_actual_usage.py" in script:
            return subprocess.CompletedProcess(args, 0, stdout="OK:AI_ACTUAL_USAGE_AUDITED status=USED\n", stderr="")
        if "audit_autonomous_runtime_readiness.py" in script:
            return subprocess.CompletedProcess(args, 0, stdout="OK:AUTONOMOUS_RUNTIME_READINESS_AUDITED status=READY\n", stderr="")
        if "audit_server_extensions_usage.py" in script:
            return subprocess.CompletedProcess(args, 0, stdout="OK:SERVER_EXTENSIONS_USAGE_AUDITED status=USED\n", stderr="")
        if "audit_repo_safety.py" in script:
            return subprocess.CompletedProcess(args, 0, stdout="OK:REPO_SAFETY_AUDITED status=SAFE\n", stderr="")
        if "audit_trading_decision_policy.py" in script:
            return subprocess.CompletedProcess(args, 0, stdout="OK:TRADING_DECISION_POLICY_AUDITED status=TIGHTEN\n", stderr="")
        if "assert_phantom_handoff_pipeline.py" in script:
            return subprocess.CompletedProcess(args, 0, stdout="OK:PHANTOM_HANDOFF_PIPELINE\n", stderr="")
        if "assert_recovery_unlock_safety.py" in script:
            return subprocess.CompletedProcess(args, 0, stdout="OK:RECOVERY_UNLOCK_SAFETY\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="OK\n", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    rc = mod.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "FINAL:BOLEH_DITINGGAL=YES" in out
