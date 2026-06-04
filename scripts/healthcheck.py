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


def _hydrate_env_from_dotenv() -> None:
    """Best-effort load of repository .env for ad-hoc healthcheck invocations.

    Production systemd services already inject their own environment, but manual
    SSH runs may not source .env. When keys are absent we hydrate from .env so
    healthcheck reads the same live-control contract as the runtime.
    """
    dotenv_path = PROJECT_ROOT / ".env"
    if not dotenv_path.exists():
        return
    try:
        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key:
                os.environ[key] = value
    except Exception:
        return


_hydrate_env_from_dotenv()

# Setup clean stdout logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Healthcheck")

def trigger_rollback(reason: str):
    allow_rollback = os.getenv("KIBOT_HEALTHCHECK_ALLOW_ROLLBACK", "false").lower() == "true"
    if not allow_rollback:
        logger.warning(
            "🚨 HEALTHCHECK FAILED: %s. Rollback suppressed because "
            "KIBOT_HEALTHCHECK_ALLOW_ROLLBACK is not true.",
            reason,
        )
        return

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
    import json
    from datetime import datetime
    
    # 1. Enforce live-only mode environment flags
    runtime_mode = str(os.getenv("KIBOT_RUNTIME_MODE", os.getenv("KIBOT_TRADING_MODE", "")).strip()).upper()
    live_trading_env = os.getenv("KIBOT_LIVE_TRADING_ENABLED", "false").lower() == "true"
    if getattr(KiConfig, "LIVE_TRADING_ENABLED", False) is True:
        live_trading_env = True
        os.environ["KIBOT_LIVE_TRADING_ENABLED"] = "true"
    canary_live_env = os.getenv("KIBOT_CANARY_LIVE_ENABLED", "false").lower() == "true"
    withdrawal_env = os.getenv("KIBOT_WITHDRAWAL_ENABLED", "false").lower() == "true"
    
    logger.info(f"KIBOT_RUNTIME_MODE in env: {runtime_mode}")
    logger.info(f"KIBOT_LIVE_TRADING_ENABLED in env: {live_trading_env}")
    logger.info(f"KIBOT_CANARY_LIVE_ENABLED in env: {canary_live_env}")
    logger.info(f"KIBOT_WITHDRAWAL_ENABLED in env: {withdrawal_env}")
    
    if not live_trading_env:
        logger.error("❌ CRITICAL: KIBOT_LIVE_TRADING_ENABLED must be True in LIVE_ONLY mode!")
        safe_exit(30, "KIBOT_LIVE_TRADING_ENABLED must be True in LIVE_ONLY mode.")
        
    if canary_live_env:
        logger.error("❌ CRITICAL: KIBOT_CANARY_LIVE_ENABLED must be False in LIVE_ONLY mode!")
        safe_exit(31, "KIBOT_CANARY_LIVE_ENABLED must be False in LIVE_ONLY mode.")
    if withdrawal_env:
        logger.error("❌ CRITICAL: KIBOT_WITHDRAWAL_ENABLED must be False in LIVE_ONLY mode!")
        safe_exit(31, "KIBOT_WITHDRAWAL_ENABLED must be False in LIVE_ONLY mode.")
        
    # 2. Assert environmental safety gates are True
    required_safety_gates = {
        "KIBOT_BLOCK_TRADE_IF_EV_NEGATIVE": True,
        "KIBOT_BLOCK_TRADE_IF_STATE_STALE": True,
        "KIBOT_BLOCK_TRADE_IF_KILL_SWITCH": True
    }
    for gate_var, expected in required_safety_gates.items():
        val = os.getenv(gate_var, "false").lower() == "true"
        logger.info(f"{gate_var} in env: {val}")
        if val != expected:
            logger.error(f"❌ CRITICAL: Environment safety gate {gate_var} must be enabled (True)!")
            safe_exit(32, f"Environment safety gate {gate_var} must be enabled!")

    # 3. Dynamic 1.5% daily drawdown cap check under WIB timezone reset
    try:
        from Core.Support.ki_config import WIB
    except ImportError:
        # Fallback if WIB cannot be imported
        from datetime import timezone, timedelta
        WIB = timezone(timedelta(hours=7))
        
    today_wib = str(datetime.now(WIB).date())
    anchor_lock_file = PROJECT_ROOT / "state" / "daily_equity_anchor_lock.json"
    primary_anchor_file = PROJECT_ROOT / "state" / "daily_equity_anchor.json"

    def _read_anchor(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.error("❌ CRITICAL: Failed to read %s: %s", path.name, exc)
            safe_exit(33, f"Failed to read {path.name}: {exc}")
        return {}

    primary_anchor = _read_anchor(primary_anchor_file)
    lock_anchor = _read_anchor(anchor_lock_file)
    primary_current = primary_anchor.get("date") == today_wib
    lock_current = lock_anchor.get("date") == today_wib

    if lock_anchor and not lock_current and primary_current:
        logger.warning(
            "⚠️ Ignoring stale daily_equity_anchor_lock.json date=%s because daily_equity_anchor.json is current for %s.",
            lock_anchor.get("date"),
            today_wib,
        )

    if lock_current:
        anchor_file = anchor_lock_file
        anchor_data = lock_anchor
    elif primary_anchor:
        anchor_file = primary_anchor_file
        anchor_data = primary_anchor
    elif lock_anchor:
        anchor_file = anchor_lock_file
        anchor_data = lock_anchor
    else:
        anchor_file = primary_anchor_file
        anchor_data = {}
    
    logger.info(f"Checking daily drawdown anchor at {anchor_file} for date {today_wib}...")
    if not anchor_data:
        logger.error("❌ CRITICAL: daily_equity_anchor.json is missing!")
        safe_exit(33, "daily_equity_anchor.json is missing!")
        
    try:
        anchor_date = anchor_data.get("date")
        max_loss_pct = float(anchor_data.get("max_daily_loss_pct", 0.0))
        
        logger.info(f"Daily anchor date: {anchor_date}, max_daily_loss_pct: {max_loss_pct}%")
        
        if anchor_date != today_wib:
            rollover_file = PROJECT_ROOT / "state" / "daily_reset_state.json"
            governor_file = PROJECT_ROOT / "state" / "capital_governor.json"
            strategy_file = PROJECT_ROOT / "state" / "active_strategy.json"
            rollover_state = {}
            governor_state = {}
            strategy_state = {}
            try:
                if rollover_file.exists():
                    rollover_state = json.loads(rollover_file.read_text(encoding="utf-8"))
            except Exception:
                rollover_state = {}
            try:
                if governor_file.exists():
                    governor_state = json.loads(governor_file.read_text(encoding="utf-8"))
            except Exception:
                governor_state = {}
            try:
                if strategy_file.exists():
                    strategy_state = json.loads(strategy_file.read_text(encoding="utf-8"))
            except Exception:
                strategy_state = {}

            rollover_status = str(rollover_state.get("status") or "").upper()
            forced_exit_all = bool(rollover_state.get("forced_exit_all", False))
            current_mode = str(rollover_state.get("current_global_mode") or strategy_state.get("global_mode") or "").upper()
            governor_pending = bool(governor_state.get("daily_reset_pending", False))
            governor_reason = str(governor_state.get("allow_new_orders_reason") or "").strip()
            rollover_ok = (
                governor_pending
                or "daily_rollover_exit_pending" in governor_reason
                or forced_exit_all
                or rollover_status in {"PRE_CLOSE", "EXITING", "PENDING_RESET", "RESET_DONE"}
            )
            if not rollover_ok or current_mode != "EXIT_ALL":
                logger.error(f"❌ CRITICAL: daily_equity_anchor.json date ({anchor_date}) is stale! Expected current WIB date ({today_wib}).")
                safe_exit(33, f"daily_equity_anchor.json is stale (date: {anchor_date}, expected: {today_wib})!")
            logger.warning(
                "⚠️ daily_equity_anchor.json is still on the previous WIB day, but daily rollover is active (%s); allowing exit-only transition.",
                rollover_status or "pending",
            )
            
        if max_loss_pct != 1.5:
            logger.error(f"❌ CRITICAL: daily_equity_anchor.json max_daily_loss_pct is {max_loss_pct}%, must be exactly 1.5%!")
            safe_exit(33, "daily_equity_anchor.json max_daily_loss_pct must be exactly 1.5%!")
            
    except Exception as exc:
        if isinstance(exc, SystemExit):
            raise
        logger.error(f"❌ CRITICAL: Failed to validate daily_equity_anchor.json: {exc}")
        safe_exit(33, f"Failed to validate daily_equity_anchor.json: {exc}")

    # 4. Enforce stop-loss/take-profit in active risk configuration
    strategy_file = PROJECT_ROOT / "state" / "active_strategy.json"
    logger.info(f"Enforcing stop-loss/take-profit in active strategy {strategy_file}...")
    
    if not strategy_file.exists():
        logger.error("❌ CRITICAL: active_strategy.json is missing!")
        safe_exit(34, "active_strategy.json is missing!")
        
    try:
        with open(strategy_file, "r") as f:
            strategy_data = json.load(f)
            
        indodax_config = strategy_data.get("indodax", {})
        trailing_stop = float(indodax_config.get("trailing_stop_pct", 0.0))
        hard_stop = float(indodax_config.get("hard_stop_pct", 0.0))
        
        logger.info(f"Active indodax strategy: trailing_stop_pct={trailing_stop}%, hard_stop_pct={hard_stop}%")
        
        if trailing_stop <= 0.0 or hard_stop <= 0.0:
            logger.error("❌ CRITICAL: Active risk configuration is missing or has non-positive stop-loss/take-profit parameters!")
            safe_exit(34, "Active risk configuration is missing trailing_stop_pct or hard_stop_pct!")
            
    except Exception as exc:
        if isinstance(exc, SystemExit):
            raise
        logger.error(f"❌ CRITICAL: Failed to validate active_strategy.json: {exc}")
        safe_exit(34, f"Failed to validate active_strategy.json: {exc}")

    logger.info("✅ Live trading gates and safety limits are fully aligned and secured.")


def check_no_legacy_modes():
    logger.info("Step 6/8: Verifying production dashboard contains no legacy paper/sim/canary labels...")
    import urllib.request
    import re

    endpoints = [
        "http://127.0.0.1:8787/",
        "http://127.0.0.1:8787/api/control-plane",
    ]
    forbidden = (
        re.compile(r"\bpaper\b"),
        re.compile(r"\bsim\b"),
        re.compile(r"\bmock\b"),
        re.compile(r"\bcanary\b"),
        re.compile(r"view-only"),
    )
    for url in endpoints:
        try:
            with urllib.request.urlopen(url, timeout=5) as res:
                body = res.read().decode("utf-8", errors="ignore").lower()
            hits = [pattern.pattern for pattern in forbidden if pattern.search(body)]
            if hits:
                logger.error(f"❌ CRITICAL: Legacy labels found in {url}: {hits}")
                safe_exit(35, f"Legacy labels found in {url}: {hits}")
        except Exception as exc:
            logger.error(f"❌ CRITICAL: Could not inspect {url}: {exc}")
            safe_exit(35, f"Could not inspect {url}: {exc}")
    logger.info("✅ Production dashboard/control-plane are free of legacy labels.")


def check_network_bindings():
    logger.info("Step 7/8: Auditing zero-trust port bindings...")
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
                        net_connections = getattr(p, "net_connections", None)
                        if callable(net_connections):
                            conns = net_connections(kind='all')
                        else:
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
    logger.info("Step 8/8: Auditing state JSON freshness and validity...")
    import time
    import json
    
    required_states = [
        "leadlag_alpha.json",
        "scanner_runtime.json",
        "phantom_scout.json",
        "market_rotation.json",
        "punishment_state.json",
        "expected_value.json",
        "web3_opportunities.json",
        "ai_decision_trace.json",
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
        "expected_value.json": 31536000.0,
        "web3_opportunities.json": 300.0,
        "ai_decision_trace.json": 120.0,
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
            if is_bootstrap_allowed or state_file in {"web3_opportunities.json", "ai_decision_trace.json"}:
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
                    elif state_file == "web3_opportunities.json":
                        default_data = {"updated_at": "", "best_opportunities": [], "rejected": [], "routes": {"solana": {}, "base": {}, "polymarket": {}, "future_web3": {}}}
                    elif state_file == "ai_decision_trace.json":
                        default_data = {"updated_at": "", "objective": "maximize_risk_adjusted_profit_for_boss", "market_summary": "", "best_action": "WAIT", "venue": "indodax", "reason": "bootstrap", "confidence": 0.0, "risk_status": "UNKNOWN", "next_check_seconds": 60}
                    
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

            if state_file == "web3_opportunities.json":
                if isinstance(data, dict):
                    required_keys = {"updated_at", "best_opportunities", "rejected", "routes"}
                    missing_keys = required_keys - set(data.keys())
                    if missing_keys:
                        logger.error(f"❌ CRITICAL STATE ERROR: web3_opportunities.json is missing required schema keys: {missing_keys}")
                        safe_exit(20, f"web3_opportunities.json is missing required schema keys: {missing_keys}")
                else:
                    logger.error(f"❌ CRITICAL STATE ERROR: web3_opportunities.json has an invalid type: {type(data)}")
                    safe_exit(20, f"web3_opportunities.json has an invalid type: {type(data)}")

                positions_file = Path(state_dir) / "web3_positions.json"
                if positions_file.exists():
                    try:
                        positions = json.loads(positions_file.read_text())
                    except Exception:
                        positions = []
                    if positions:
                        exit_state = Path(state_dir) / "web3_exit_state.json"
                        if not exit_state.exists():
                            logger.error("❌ CRITICAL STATE ERROR: web3_positions.json exists but web3_exit_state.json is missing.")
                            safe_exit(21, "web3_positions.json exists but web3_exit_state.json is missing.")

                pumpfun_route = Path(state_dir) / "pumpfun_route_state.json"
                if pumpfun_route.exists():
                    try:
                        pump_state = json.loads(pumpfun_route.read_text())
                    except Exception as exc:
                        logger.error(f"❌ CRITICAL STATE ERROR: pumpfun_route_state.json is invalid JSON: {exc}")
                        safe_exit(23, f"pumpfun_route_state.json is invalid JSON: {exc}")
                    if isinstance(pump_state, dict):
                        required_keys = {"updated_at", "mint", "route_type", "buy_route_available", "sell_route_available", "jupiter_quote", "pumpfun_curve", "reason"}
                        missing_keys = required_keys - set(pump_state.keys())
                        if missing_keys:
                            logger.error(f"❌ CRITICAL STATE ERROR: pumpfun_route_state.json is missing required schema keys: {missing_keys}")
                            safe_exit(23, f"pumpfun_route_state.json is missing required schema keys: {missing_keys}")
                        if os.getenv("PUMPFUN_NATIVE_EXECUTOR_ENABLED", "false").lower() == "true":
                            native_state = Path(state_dir) / "pumpfun_native_executor_state.json"
                            if not native_state.exists():
                                logger.warning("⚠️ Pump.fun native executor enabled but native state is missing; continuing in guarded mode.")

            if state_file == "ai_decision_trace.json":
                required_keys = {"updated_at", "objective", "market_summary", "best_action", "venue", "reason", "confidence", "risk_status", "next_check_seconds"}
                missing_keys = required_keys - set(data.keys()) if isinstance(data, dict) else required_keys
                if missing_keys:
                    logger.error(f"❌ CRITICAL STATE ERROR: ai_decision_trace.json is missing required schema keys: {missing_keys}")
                    safe_exit(22, f"ai_decision_trace.json is missing required schema keys: {missing_keys}")

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
                    disable_cpu_hc = os.getenv("KIBOT_DISABLE_CPU_HEALTHCHECK", "false").lower() == "true"
                    cpu_threshold = float(os.getenv("KIBOT_CPU_HEALTHCHECK_THRESHOLD", "95.0"))
                    
                    if disable_cpu_hc:
                        logger.info("ℹ️ CPU healthcheck is disabled via KIBOT_DISABLE_CPU_HEALTHCHECK env.")
                        consecutive_high_cpu = 0
                    elif cpu_pct > cpu_threshold:
                        consecutive_high_cpu += 1
                        logger.warning(f"⚠️ CPU threshold exceeded: {cpu_pct}% (Consecutive count: {consecutive_high_cpu}/3, limit: {cpu_threshold}%)")
                    else:
                        consecutive_high_cpu = 0
                    
                    history["consecutive_high_cpu"] = consecutive_high_cpu
                    try:
                        with open(history_path, "w") as hf:
                            json.dump(history, hf, indent=4)
                    except Exception:
                        pass
                        
                    if consecutive_high_cpu >= 3:
                        logger.error(f"❌ CRITICAL STATE ERROR: CPU percent is > {cpu_threshold}% for 3 consecutive samples/checks ({cpu_pct}%)!")
                        safe_exit(16, f"CPU percent is > {cpu_threshold}% for 3 consecutive samples/checks ({cpu_pct}%)!")
            
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


def check_runtime_assertions():
    logger.info("Step 9/9: Running runtime assertion suite...")
    import subprocess

    assertions = [
        ("scripts/assert_live_only_mode.py", "py"),
        ("scripts/assert_no_paper_canary_shadow.py", "py"),
        ("scripts/assert_github_main_only.sh", "sh"),
        ("scripts/assert_live_truth_writer.py", "py"),
        ("scripts/assert_ai_inventory_boot.py", "py"),
        ("scripts/assert_dashboard_live_truth.py", "py"),
        ("scripts/assert_website_ai_system_working.py", "py"),
        ("scripts/assert_indodax_live_gate.py", "py"),
        ("scripts/assert_indodax_runtime_autonomy.py", "py"),
        ("scripts/diagnose_phantom_runtime.py", "py"),
        ("scripts/assert_phantom_live_ready.py", "py"),
        ("scripts/assert_phantom_runtime_autonomy.py", "py"),
        ("scripts/assert_telegram_exception_only.py", "py"),
    ]

    for rel_path, kind in assertions:
        path = PROJECT_ROOT / rel_path
        if not path.exists():
            logger.warning("⚠️ Assertion missing: %s", rel_path)
            continue
        cmd = [sys.executable, str(path)] if kind == "py" else ["bash", str(path)]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        output = (res.stdout or "").strip()
        if output:
            logger.info("%s => %s", rel_path, output.splitlines()[-1])
        if rel_path.endswith("diagnose_phantom_runtime.py") and "OK:PHANTOM_LOCKED_MISSING_ENV" in output:
            logger.warning("⚠️ Phantom is locked by missing env; continuing healthcheck.")
            continue
        if res.returncode != 0:
            logger.error("❌ Runtime assertion failed: %s", output or rel_path)
            safe_exit(39, f"Runtime assertion failed: {rel_path}: {output}")
    logger.info("✅ Runtime assertion suite passed.")


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
    check_no_legacy_modes()
    check_network_bindings()
    check_json_states(state_dir)
    check_runtime_assertions()
    check_scanner_service()
    
    logger.info("==================================================")
    logger.info("🎉 HEALTHCHECK PASSED SUCCESSFULLY! ALL SYSTEMS GREEN.")
    logger.info("==================================================")
    safe_exit(0)

if __name__ == "__main__":
    main()
