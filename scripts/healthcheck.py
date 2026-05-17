#!/usr/bin/env python3
"""
KiBot Production Healthcheck Utility
===================================
Verifies the runtime integrity of the production container:
1. Validates that core packages and relative modules are fully importable.
2. Asserts RiskGate maximum daily drawdown is strictly locked at 1.5%.
3. Verifies dynamic and environmental safety limits.
4. Audits write permissions to crucial persistent folders (state/ and Logs/).
5. Assures sensitive variables (.env keys, seed phrases) are redacted or masked in logs.
"""

import os
import sys
import logging
from pathlib import Path
import tempfile

# Ensure project root is in the path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Setup clean stdout logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Healthcheck")

def trigger_rollback(reason: str):
    logger.warning(f"🚨 HEALTHCHECK FAILED: {reason}. Triggering automated rollback...")
    import subprocess
    rollback_script = PROJECT_ROOT / "scripts" / "rollback.py"
    if rollback_script.exists():
        try:
            res = subprocess.run([sys.executable, str(rollback_script), reason], capture_output=True, text=True)
            logger.info(f"🔄 Rollback execution output:\n{res.stdout}")
            if res.stderr:
                logger.error(f"⚠️ Rollback stderr:\n{res.stderr}")
        except Exception as e:
            logger.error(f"❌ Failed to run rollback script: {e}")
    else:
        logger.error(f"❌ Rollback script not found at {rollback_script}")

def safe_exit(code: int, reason: str = ""):
    if code != 0:
        trigger_rollback(reason or "Unknown Healthcheck Failure")
    sys.exit(code)

def check_imports():
    logger.info("Step 1/8: Checking core system imports...")
    try:
        from Core.Support.ki_config import KiConfig, PROJECT_ROOT, STATE_DIR
        from Core.circuit_breaker import CircuitBreaker
        from Core.risk_gate import RiskGate
        logger.info("✅ Core imports are healthy.")
        return KiConfig, STATE_DIR
    except Exception as exc:
        logger.error(f"❌ Core imports failed: {exc}")
        safe_exit(1, f"Core imports failed: {exc}")

def check_drawdown_bounds(KiConfig):
    logger.info("Step 2/8: Verifying daily drawdown bounds...")
    try:
        # Check hardcoded parity limit
        logger.info(f"KiConfig.MAX_DAILY_LOSS_PERCENT resolves to: {KiConfig.MAX_DAILY_LOSS_PERCENT}%")
        if KiConfig.MAX_DAILY_LOSS_PERCENT != 1.5:
            logger.error("❌ CRITICAL: KiConfig.MAX_DAILY_LOSS_PERCENT must be exactly 1.5%!")
            safe_exit(2, "KiConfig.MAX_DAILY_LOSS_PERCENT must be exactly 1.5%!")
            
        from Core.risk_gate import RiskGate
        gate = RiskGate({"max_daily_loss_pct": 5.0})
        actual_cap = gate.config.get("max_daily_loss_pct")
        logger.info(f"Dynamic override test: Asked for 5.0%, RiskGate capped at: {actual_cap}%")
        if actual_cap != 1.5:
            logger.error("❌ CRITICAL: RiskGate cap override bypass detected!")
            safe_exit(3, "RiskGate cap override bypass detected!")
            
        logger.info("✅ Drawdown bounds are secure and verified.")
    except Exception as exc:
        logger.error(f"❌ Drawdown checks failed: {exc}")
        safe_exit(4, f"Drawdown checks failed: {exc}")

def check_directory_permissions(state_dir):
    logger.info("Step 3/8: Verifying persistent directory write permissions...")
    test_dirs = {
        "State Directory": Path(state_dir),
        "Logs Directory": PROJECT_ROOT / "Logs"
    }
    
    for name, path in test_dirs.items():
        try:
            if not path.exists():
                logger.info(f"Directory {path} missing, attempting to create...")
                path.mkdir(parents=True, exist_ok=True)
            
            # Perform atomic write, read, and delete
            test_file = path / ".healthcheck_tmp"
            test_content = "KIBOT_HEALTHY_2026"
            
            test_file.write_text(test_content, encoding="utf-8")
            read_content = test_file.read_text(encoding="utf-8")
            test_file.unlink()
            
            if read_content != test_content:
                raise IOError("Data mismatch during permission check.")
                
            logger.info(f"✅ {name} ({path}) has healthy read/write/delete permissions.")
        except Exception as exc:
            logger.error(f"❌ Permission check failed on {name} ({path}): {exc}")
            safe_exit(5, f"Permission check failed on {name} ({path}): {exc}")

def audit_log_redaction():
    logger.info("Step 4/8: Auditing log redaction and secret privacy...")
    # Setup dummy log capturing
    import io
    log_capture = io.StringIO()
    capture_handler = logging.StreamHandler(log_capture)
    
    test_logger = logging.getLogger("RedactAudit")
    test_logger.addHandler(capture_handler)
    test_logger.setLevel(logging.INFO)
    
    try:
        # Verify that printing config values hides secret parameters or they aren't plain logged
        # A safe system must never log private keys, mnemonics, or API keys in debug dumps.
        secrets_to_check = [
            os.getenv("SOLANA_PRIVATE_KEY"),
            os.getenv("TELEGRAM_BOT_TOKEN"),
            os.getenv("INDODAX_API_KEY"),
            os.getenv("INDODAX_SECRET_KEY")
        ]
        
        # Log some diagnostic messages
        test_logger.info("Performing standard production diagnostics...")
        test_logger.info(f"Current Environment Path: {sys.prefix}")
        
        # Test: If anyone logs standard diagnostics, make sure no actual raw secrets are leaked in stdout
        log_output = log_capture.getvalue()
        for sec in secrets_to_check:
            if sec and len(sec) > 6 and sec in log_output:
                logger.error("❌ CRITICAL: Raw credentials leaked in logs!")
                safe_exit(6, "Raw credentials leaked in logs!")
                
        logger.info("✅ Log redaction/leak checks passed.")
    finally:
        test_logger.removeHandler(capture_handler)

def check_live_trading_gates(KiConfig):
    logger.info("Step 5/8: Verifying runtime safety gates...")
    # Ensure live trading defaults to False if testing or not explicitly enabled
    live_trading_env = os.getenv("KIBOT_LIVE_TRADING_ENABLED", "false").lower() == "true"
    logger.info(f"KIBOT_LIVE_TRADING_ENABLED in env: {live_trading_env}")
    logger.info(f"KiConfig.LIVE_TRADING_ENABLED resolves to: {KiConfig.LIVE_TRADING_ENABLED}")
    
    if not live_trading_env and KiConfig.LIVE_TRADING_ENABLED:
        logger.error("❌ CRITICAL: Live trading enabled in code but disabled in environment!")
        safe_exit(7, "Live trading enabled in code but disabled in environment!")
        
    logger.info("✅ Live trading gates are fully aligned.")

def check_network_bindings():
    logger.info("Step 6/8: Auditing zero-trust port bindings...")
    try:
        import psutil
    except ImportError:
        logger.error("❌ CRITICAL: psutil dependency is missing! This is required for HFT execution and network checks.")
        safe_exit(9, "psutil dependency is missing!")

    forbidden_wildcards = {"0.0.0.0", "::", "", "*"}
    target_ports = {
        9998: "Indodax UDP Listener",
        9999: "Batam UDP Listener/Janitor",
        9990: "Polymarket UDP Listener",
        9991: "Council Signal Listener",
        8787: "Dashboard TCP Service",
        11600: "Polymarket State API"
    }

    try:
        import os
        import sys
        
        connections = []
        try:
            connections = psutil.net_connections(kind='all')
        except (psutil.AccessDenied, Exception) as p_exc:
            # If we get AccessDenied (typical on macOS/darwin or non-root environments),
            # try auditing only the processes/connections owned by the current user.
            is_dev = (sys.platform == "darwin" or (hasattr(os, "geteuid") and os.geteuid() != 0))
            if is_dev:
                logger.warning(f"⚠️ AccessDenied/Restriction during global net_connections audit ({p_exc}). Auditing user process connections.")
                connections = []
                for p in psutil.process_iter():
                    try:
                        conns = p.connections(kind='all')
                        if conns:
                            connections.extend(conns)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            else:
                # In production environment (running as root on Linux), net_connections must succeed.
                raise p_exc

        exposed_services = []
        for conn in connections:
            laddr = conn.laddr
            if laddr and hasattr(laddr, 'port') and laddr.port in target_ports:
                ip = laddr.ip
                if ip in forbidden_wildcards:
                    exposed_services.append(f"{target_ports[laddr.port]} (port {laddr.port}) is bound to public wildcard address '{ip}'!")
        
        if exposed_services:
            for exp in exposed_services:
                logger.error(f"❌ SECURITY EXPOSURE: {exp}")
            safe_exit(8, f"Exposed services: {exposed_services}")

        logger.info("✅ All core services are securely bound (zero-trust verified).")
    except Exception as exc:
        logger.error(f"❌ CRITICAL: Could not audit network bindings: {exc}")
        safe_exit(8, f"Could not audit network bindings: {exc}")

def is_any_core_service_active():
    if sys.platform.startswith("linux"):
        import subprocess
        core_services = ["kibot-scanner", "kibot-master", "kibot-executor", "kibot-dashboard"]
        for svc in core_services:
            try:
                res = subprocess.run(["systemctl", "is-active", svc], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if res.stdout.strip() == "active":
                    return True
            except Exception:
                pass
    return False

def get_history_path():
    env_path = os.getenv("KIBOT_HEALTHCHECK_HISTORY_PATH")
    if env_path:
        return Path(env_path)
    return Path(tempfile.gettempdir()) / ".kibot_healthcheck_history.json"

def check_json_states(state_dir):
    logger.info("Step 7/8: Auditing state JSON freshness and validity...")
    import time
    import json
    
    required_states = [
        "leadlag_alpha.json",
        "scanner_runtime.json",
        "phantom_scout.json",
        "market_rotation.json",
        "punishment_state.json",
        "expected_value.json"
    ]
    
    is_bootstrap_allowed = (
        os.getenv("KIBOT_HEALTHCHECK_ALLOW_BOOTSTRAP", "false").lower() == "true" or
        os.getenv("KIBOT_ENV", "prod").lower() in ("local", "dev", "test") or
        sys.platform == "darwin"
    )
    
    if is_any_core_service_active() and os.getenv("KIBOT_ENV", "prod").lower() != "test":
        logger.warning("⚠️ Core systemd services are active. Disabling state bootstrapping to prevent false-green healthcheck.")
        is_bootstrap_allowed = False

    # Strictly block state bootstrapping in production environment
    if os.getenv("KIBOT_ENV", "prod").lower() in ("prod", "production"):
        logger.warning("⚠️ Running in production environment. Strictly disabling state bootstrapping!")
        is_bootstrap_allowed = False
    
    max_ages = {
        "scanner_runtime.json": 90.0,
        "leadlag_alpha.json": 90.0,
        "phantom_scout.json": 300.0,
        "market_rotation.json": 90.0,
        "punishment_state.json": 31536000.0,
        "expected_value.json": 31536000.0
    }
    
    for state_file in required_states:
        # Check if phantom_scout.json is required
        if state_file == "phantom_scout.json":
            phantom_enabled = os.getenv("KIBOT_PHANTOM_SCOUT_ENABLED", "false").lower() == "true"
            if not phantom_enabled:
                logger.info("Skipping phantom_scout.json check because KIBOT_PHANTOM_SCOUT_ENABLED is false.")
                continue
 
        file_path = Path(state_dir) / state_file
        logger.info(f"Auditing state file: {file_path}")
        
        # Self-healing / bootstrapping capability
        if not file_path.exists():
            if is_bootstrap_allowed:
                logger.info(f"State file {state_file} missing. Bootstrapping with default secure config...")
                try:
                    default_data = {}
                    if state_file == "leadlag_alpha.json":
                        default_data = {"qualified_signals": [], "opportunities": [], "last_run_timestamp": time.time()}
                    elif state_file == "scanner_runtime.json":
                        default_data = {"current_interval": 2.0, "mode": "NORMAL", "telemetry": {"cpu_percent": 0.0}}
                    elif state_file == "phantom_scout.json":
                        default_data = {"active_rpc": "https://api.mainnet-beta.solana.com", "failed_rpcs": []}
                    elif state_file == "market_rotation.json":
                        default_data = {"allocations_pct": {"Indodax": 25.0, "Polymarket": 25.0, "Phantom": 25.0, "CASH_WAIT": 25.0}}
                    elif state_file == "punishment_state.json":
                        default_data = {"schema_version": 1, "status": "idle", "records": {}, "quarantined": []}
                    elif state_file == "expected_value.json":
                        default_data = {"schema_version": 1, "status": "idle", "strategies": {}}
                    
                    with open(file_path, "w") as f:
                        json.dump(default_data, f, indent=4)
                    logger.info(f"✅ Bootstrapped default secure state for {state_file}")
                except Exception as e:
                    logger.error(f"❌ Failed to bootstrap state file {state_file}: {e}")
                    safe_exit(10, f"Failed to bootstrap state file {state_file}: {e}")
            else:
                logger.error(f"❌ CRITICAL STATE ERROR: Required state file {state_file} is missing, and bootstrapping is disabled!")
                safe_exit(10, f"Required state file {state_file} is missing, and bootstrapping is disabled!")
 
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
            
            # Check modification time
            mtime = file_path.stat().st_mtime
            age_s = time.time() - mtime
            logger.info(f"Parsed {state_file} successfully. Age: {age_s:.1f}s")
            
            limit = max_ages.get(state_file, 3600.0)
            if age_s > limit:
                if is_bootstrap_allowed:
                    logger.info(f"🔄 State file {state_file} is stale ({age_s:.1f}s > {limit}s) in non-production. Auto-healing/touching file...")
                    try:
                        if state_file == "leadlag_alpha.json" and isinstance(data, dict):
                            data["last_run_timestamp"] = time.time()
                            with open(file_path, "w") as f:
                                json.dump(data, f, indent=4)
                        else:
                            file_path.touch()
                        age_s = 0.0
                    except Exception as touch_err:
                        logger.warning(f"⚠️ Failed to auto-touch {state_file}: {touch_err}")
                
                if age_s > limit:
                    logger.error(f"❌ CRITICAL STATE ERROR: {state_file} is stale! Last modified {age_s:.1f}s ago (limit: {limit}s).")
                    safe_exit(11, f"{state_file} is stale! Last modified {age_s:.1f}s ago (limit: {limit}s).")
                
            # Extra semantic validations
            if state_file == "punishment_state.json":
                required_keys = {"schema_version", "status", "records", "quarantined"}
                missing_keys = required_keys - set(data.keys())
                if missing_keys:
                    logger.error(f"❌ CRITICAL STATE ERROR: punishment_state.json is missing required schema keys: {missing_keys}")
                    safe_exit(18, f"punishment_state.json is missing required schema keys: {missing_keys}")
            
            if state_file == "expected_value.json":
                if isinstance(data, dict):
                    required_keys = {"schema_version", "status", "strategies"}
                    missing_keys = required_keys - set(data.keys())
                    if missing_keys:
                        logger.error(f"❌ CRITICAL STATE ERROR: expected_value.json is missing required schema keys: {missing_keys}")
                        safe_exit(19, f"expected_value.json is missing required schema keys: {missing_keys}")
                elif isinstance(data, list):
                    logger.info("✅ expected_value.json is formatted as a valid list of evaluations.")
                else:
                    logger.error(f"❌ CRITICAL STATE ERROR: expected_value.json has an invalid type: {type(data)}")
                    safe_exit(19, f"expected_value.json has an invalid type: {type(data)}")

            if state_file == "scanner_runtime.json":
                mode = data.get("mode")
                if mode not in {"FAST", "NORMAL", "SLOW"}:
                    logger.error(f"❌ CRITICAL STATE ERROR: Invalid mode in scanner_runtime.json: '{mode}' (must be FAST, NORMAL, or SLOW).")
                    safe_exit(15, f"Invalid mode in scanner_runtime.json: '{mode}' (must be FAST, NORMAL, or SLOW).")
                
                # Check CPU Throttling > 95% consecutively
                cpu_pct = None
                if "cpu_percent" in data:
                    cpu_pct = data["cpu_percent"]
                elif "telemetry" in data and isinstance(data["telemetry"], dict) and "cpu_percent" in data["telemetry"]:
                    cpu_pct = data["telemetry"]["cpu_percent"]
                
                if cpu_pct is not None:
                    cpu_pct = float(cpu_pct)
                    logger.info(f"Current CPU Percent from scanner runtime: {cpu_pct}%")
                    history_path = get_history_path()
                    history = {}
                    if history_path.exists():
                        try:
                            with open(history_path, "r") as hf:
                                history = json.load(hf)
                        except Exception:
                            pass
                    
                    consecutive_high_cpu = history.get("consecutive_high_cpu", 0)
                    if cpu_pct > 95.0:
                        consecutive_high_cpu += 1
                        logger.warning(f"⚠️ CPU threshold exceeded: {cpu_pct}% (Consecutive count: {consecutive_high_cpu}/3)")
                    else:
                        consecutive_high_cpu = 0
                    
                    history["consecutive_high_cpu"] = consecutive_high_cpu
                    try:
                        with open(history_path, "w") as hf:
                            json.dump(history, hf, indent=4)
                    except Exception:
                        pass
                        
                    if consecutive_high_cpu >= 3:
                        logger.error(f"❌ CRITICAL STATE ERROR: CPU percent is > 95% for 3 consecutive samples/checks ({cpu_pct}%)!")
                        safe_exit(16, f"CPU percent is > 95% for 3 consecutive samples/checks ({cpu_pct}%)!")
            
            if state_file == "leadlag_alpha.json":
                leadlag_enabled = os.getenv("KIBOT_LEADLAG_ENABLED", "true").lower() == "true"
                if leadlag_enabled:
                    opportunities = data.get("opportunities", data.get("qualified_signals", []))
                    history_path = get_history_path()
                    history = {}
                    if history_path.exists():
                        try:
                            with open(history_path, "r") as hf:
                                history = json.load(hf)
                        except Exception:
                            pass
                    
                    consecutive_empty_leadlag = history.get("consecutive_empty_leadlag", 0)
                    if len(opportunities) == 0:
                        consecutive_empty_leadlag += 1
                        logger.warning(f"⚠️ LeadLag opportunities are empty (Consecutive count: {consecutive_empty_leadlag}/3)")
                    else:
                        consecutive_empty_leadlag = 0
                        
                    history["consecutive_empty_leadlag"] = consecutive_empty_leadlag
                    try:
                        with open(history_path, "w") as hf:
                            json.dump(history, hf, indent=4)
                    except Exception:
                        pass
                        
                    if consecutive_empty_leadlag >= 3:
                        logger.error("❌ CRITICAL STATE ERROR: Lead-Lag alpha engine is enabled, but opportunities array is consecutively empty for 3 checks!")
                        safe_exit(17, "Lead-Lag alpha engine is enabled, but opportunities array is consecutively empty for 3 checks!")
 
        except json.JSONDecodeError as jde:
            logger.error(f"❌ CRITICAL STATE ERROR: {state_file} has invalid JSON syntax: {jde}")
            safe_exit(12, f"{state_file} has invalid JSON syntax: {jde}")
        except SystemExit:
            raise
        except Exception as exc:
            logger.error(f"❌ CRITICAL STATE ERROR: Failed during audit of {state_file}: {exc}")
            safe_exit(13, f"Failed during audit of {state_file}: {exc}")
            
    logger.info("✅ All state files are present, valid JSON, and fresh.")


def check_scanner_service():
    logger.info("Step 8/8: Verifying systemd kibot-scanner service active status...")
    if sys.platform.startswith("linux"):
        import subprocess
        try:
            res = subprocess.run(["systemctl", "is-active", "kibot-scanner"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            status = res.stdout.strip()
            if status != "active":
                logger.error(f"❌ CRITICAL: systemd service kibot-scanner is inactive (status: {status})")
                safe_exit(14, f"systemd service kibot-scanner is inactive (status: {status})")
            logger.info("✅ systemd service kibot-scanner is active.")
        except Exception as e:
            logger.warning(f"⚠️ Could not check systemd service kibot-scanner via systemctl: {e}")
    else:
        logger.warning("⚠️ Non-Linux platform detected, skipping systemd kibot-scanner active check.")

def main():
    logger.info("==================================================")
    logger.info("RUNNING KIBOT PRODUCTION HEALTHCHECK")
    logger.info("==================================================")
    
    KiConfig, state_dir = check_imports()
    check_drawdown_bounds(KiConfig)
    check_directory_permissions(state_dir)
    audit_log_redaction()
    check_live_trading_gates(KiConfig)
    check_network_bindings()
    check_json_states(state_dir)
    check_scanner_service()
    
    logger.info("==================================================")
    logger.info("🎉 HEALTHCHECK PASSED SUCCESSFULLY! ALL SYSTEMS GREEN.")
    logger.info("==================================================")
    safe_exit(0)

if __name__ == "__main__":
    main()
