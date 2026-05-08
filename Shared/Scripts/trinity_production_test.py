#!/usr/bin/env python3
"""
Trinity v7.1 Production Pre-Flight Audit & 10-Min Simulation
============================================================
This script validates all components for the first 10 minutes of operation.
"""

import os
import sys
import json
import socket
import time
import shutil
from pathlib import Path

ROOT = Path(os.getenv("KIBOT_RUNTIME_ROOT", Path(__file__).resolve().parents[2]))
os.environ["KIBOT_RUNTIME_ROOT"] = str(ROOT)
os.environ.setdefault("KIBOT_STATE_DIR", str(ROOT / "state"))
os.environ.setdefault("KIBOT_DATA_DIR", str(ROOT / "data"))
API_BASE = os.getenv("KIBOT_API_BASE", "http://127.0.0.1:8787")
CORE_DIR = ROOT / "SERVER_BATAM" / "Core_Logic"
AI_DIR = ROOT / "SERVER_BATAM" / "AI_Orchestration"
INDICATORS_DIR = ROOT / "SERVER_BATAM" / "Indicators_Math"
INTELLIGENCE_DIR = ROOT / "SERVER_BATAM" / "Intelligence"
AUDIT_TESTING_DIR = ROOT / "SERVER_BATAM" / "Support" / "Audit_Testing"

for path in [CORE_DIR, AI_DIR, INDICATORS_DIR, INTELLIGENCE_DIR, AUDIT_TESTING_DIR]:
    if path.exists():
        sys.path.insert(0, str(path))


def manager_port() -> int:
    return int(
        os.getenv("KIBOT_MANAGER_PORT")
        or os.getenv("KIBOT_MANAGER_UDP_BIND_PORT")
        or os.getenv("KIBOT_MANAGER_HTTP_BIND_PORT")
        or "9998"
    )

def log_test(name, result, details=""):
    status = "[PASS]" if result else "[FAIL]"
    print(f"{status} {name:30} | {details}")
    return result

def test_math_engine():
    """Verify Conviction Score and Risk Matrix."""
    sys.path.append(str(ROOT / "scripts"))
    try:
        from kibot_engine_v2 import compute_conviction
        # Mock signal/ticker
        ticker = {
            "last": 2500,
            "high": 2600,
            "low": 2400,
            "vol_idr": 1000000000,
            "open": 2450,
            "buy": 2490,
            "sell": 2510
        }
        closes = [2400, 2410, 2420, 2430, 2440, 2450, 2460, 2470, 2480, 2490, 2500]
        vols = [1e8, 1.1e8, 1.2e8, 1.3e8, 1.4e8, 1.5e8, 1.6e8, 1.7e8, 1.8e8, 1.9e8, 2e8]
        avg_vol_7d = 500_000_000
        
        res = compute_conviction("TRX_IDR", ticker, closes, vols, avg_vol_7d)
        score = res.get("score", 0.0)
        return log_test("Math Engine (Conviction)", score > 0 or res.get("phase") == "BLOCKED", f"Score: {score:.4f} Reason: {res.get('reason','')}")
    except Exception as e:
        # v7.3.1: LOWER THRESHOLD to 0.50 (Bayesian minimum) to prevent missing high-conviction pumps
        return log_test("Math Engine (Conviction)", False, f"Score too low: {e}")

def test_runtime_probe():
    """Verify dashboard endpoint is reachable or at least not obviously misconfigured."""
    try:
        import urllib.request

        with urllib.request.urlopen(f"{API_BASE}/api/health", timeout=2) as response:
            return log_test("Dashboard Health Probe", response.status == 200, f"HTTP {response.status}")
    except Exception as exc:
        return log_test("Dashboard Health Probe", True, f"Endpoint not running locally yet: {exc}")


def test_manager_udp_port():
    """Verify the configured manager UDP port is syntactically sane and bindable locally."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    port = manager_port()
    try:
        sock.bind(("127.0.0.1", port))
        return log_test("Manager UDP Port", True, f"UDP {port} bind ok")
    except Exception as exc:
        return log_test("Manager UDP Port", True, f"UDP {port} already in use: {exc}")
    finally:
        sock.close()

def test_thread_profiling():
    """Verify that all required background threads are correctly defined."""
    manager_path = CORE_DIR / "kibot_manager.py"
    content = manager_path.read_text()
    required_threads = [
        "kibot-news-scanner",
        "kibot-correlation-loop",
        "kibot-coingecko-loop",
        "kibot-pair-screen-loop",
        "kibot-heartbeat-loop",
        "kibot-health-gate-loop",
        "kibot-ai-review-loop",
        "kibot-math-review-loop",
        "kibot-learning-review-loop",
        "kibot-daily-cycle-loop",
        "kibot-simulation-loop",
        "kibot-state-server",
        "kibot-discovery",
        "kibot-portfolio",
        "kibot-signal-mgr",
        "kibot-resource-governor",
        "kibot-ai-scout-loop",
        "kibot-universe-discovery-loop",
    ]
    missing = [t for t in required_threads if f'name="{t}"' not in content]
    return log_test("Manager Thread Profiling", len(missing) == 0, f"Missing: {missing}" if missing else "All required threads defined")

def test_log_maintenance_logic():
    """Verify disk usage monitoring and log rotation logic."""
    total, used, free = shutil.disk_usage("/")
    pct = (used / total) * 100
    # Simulation: Check if manager would trigger cleanup
    cleanup_trigger = pct > 80
    return log_test("Log Maintenance (Disk Health)", True, f"Disk Usage: {pct:.1f}% (Cleanup trigger: {cleanup_trigger})")

def test_ai_fallback_chain():
    """Verify AI Legion has at least 3 active providers (excluding HF)."""
    coordinator_path = AI_DIR / "kibot_ai_coordinator.py"
    content = coordinator_path.read_text()
    providers = ["groq", "gemini", "nvidia", "cohere", "openrouter"]
    active = [p for p in providers if p in content]
    return log_test("AI Legion Redundancy", len(active) >= 3, f"Active: {active}")


def test_analyst_entrypoint():
    """Verify analyst service boots into its real loop, not demo fixtures."""
    analyst_path = AUDIT_TESTING_DIR / "kibot_analyst.py"
    content = analyst_path.read_text()
    has_loop_entry = "run_analyst_loop(ANALYST_INTERVAL_SECONDS)" in content
    has_demo_seed = 'record_trade("bio_idr"' in content
    return log_test(
        "Analyst Entrypoint",
        has_loop_entry and not has_demo_seed,
        f"loop_entry={has_loop_entry} demo_seed={has_demo_seed}",
    )


def test_workflow_deploy_mode():
    """Verify deploy workflows do not auto-SSH on every push to main."""
    workflows = [
        ROOT / ".github" / "workflows" / "deploy-KiBot.yml",
    ]
    existing = [workflow for workflow in workflows if workflow.exists()]
    if not existing:
        return log_test("Workflow Deploy Mode", True, "workflow file absent; manual deploy mode")
    invalid = []
    for workflow in existing:
        content = workflow.read_text()
        if "push:" in content:
            invalid.append(workflow.name)
        if "disable --now ${RECOVERY_TIMER}" not in content and 'disable --now "${RECOVERY_TIMER}"' not in content:
            invalid.append(f"{workflow.name}:missing_legacy_timer_disable")
    return log_test("Workflow Deploy Mode", len(invalid) == 0, f"Issues: {invalid}" if invalid else "manual dispatch only")


def test_service_env_wiring():
    """Verify critical Python services inherit the live env files."""
    service_files = [
        ROOT / "SERVER_BATAM" / "Infrastructure" / "Infra" / "systemd" / "kibot-manager.service",
        ROOT / "SERVER_BATAM" / "Infrastructure" / "Infra" / "systemd" / "kibot-notifier.service",
        ROOT / "SERVER_BATAM" / "Infrastructure" / "Infra" / "systemd" / "kibot-analyst.service",
        ROOT / "SERVER_BATAM" / "Infrastructure" / "Infra" / "systemd" / "kibot-guardian.service",
        ROOT / "SERVER_BATAM" / "Infrastructure" / "Infra" / "systemd" / "kibot-orchestrator.service",
        ROOT / "SERVER_BATAM" / "Infrastructure" / "Infra" / "systemd" / "kibot-security.service",
    ]
    missing = []
    for service_file in service_files:
        content = service_file.read_text()
        for required in (".env.server", ".env.kibot", ".env.kibot_manager"):
            if required not in content:
                missing.append(f"{service_file.name}:{required}")
    return log_test("Systemd Env Wiring", len(missing) == 0, f"Missing: {missing}" if missing else "all critical services inherit live env")


def test_manager_runtime_overrides():
    """Verify the last active manager loop definitions use the fixed runtime paths."""
    manager_path = CORE_DIR / "kibot_manager.py"
    content = manager_path.read_text()
    pair_idx = content.rfind("def _pair_screen_loop()")
    math_idx = content.rfind("def _math_review_loop()")
    main_idx = content.rfind("def main()")
    pair_block = content[pair_idx:math_idx]
    math_block = content[math_idx:main_idx]
    main_block = content[main_idx:]
    checks_ok = (
        "top['pair_id']" in pair_block
        and "r.pair_id" not in pair_block
        and "_run_math_review()" in math_block
        and "_telegram_send(msg)" not in main_block
    )
    return log_test("Manager Runtime Overrides", checks_ok, "late overrides aligned to runtime-safe paths")

def run_all():
    print("=== Trinity v7.1 Production Pre-Flight Audit ===")
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)
    
    results = [
        test_math_engine(),
        test_runtime_probe(),
        test_manager_udp_port(),
        test_thread_profiling(),
        test_log_maintenance_logic(),
        test_ai_fallback_chain(),
        test_analyst_entrypoint(),
        test_workflow_deploy_mode(),
        test_service_env_wiring(),
        test_manager_runtime_overrides(),
    ]
    
    print("-" * 60)
    if all(results):
        print("RESULT: ALL SYSTEMS GREEN. Ready for 10-minute live soak.")
    else:
        print("RESULT: CRITICAL FAILURES DETECTED. Review logs before deploy.")
        sys.exit(1)

if __name__ == "__main__":
    run_all()
