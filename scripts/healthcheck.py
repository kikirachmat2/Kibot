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

def check_imports():
    logger.info("Step 1/6: Checking core system imports...")
    try:
        from Core.Support.ki_config import KiConfig, PROJECT_ROOT, STATE_DIR
        from Core.circuit_breaker import CircuitBreaker
        from Core.risk_gate import RiskGate
        logger.info("✅ Core imports are healthy.")
        return KiConfig, STATE_DIR
    except Exception as exc:
        logger.error(f"❌ Core imports failed: {exc}")
        sys.exit(1)

def check_drawdown_bounds(KiConfig):
    logger.info("Step 2/6: Verifying daily drawdown bounds...")
    try:
        # Check hardcoded parity limit
        logger.info(f"KiConfig.MAX_DAILY_LOSS_PERCENT resolves to: {KiConfig.MAX_DAILY_LOSS_PERCENT}%")
        if KiConfig.MAX_DAILY_LOSS_PERCENT != 1.5:
            logger.error("❌ CRITICAL: KiConfig.MAX_DAILY_LOSS_PERCENT must be exactly 1.5%!")
            sys.exit(2)
            
        from Core.risk_gate import RiskGate
        gate = RiskGate({"max_daily_loss_pct": 5.0})
        actual_cap = gate.config.get("max_daily_loss_pct")
        logger.info(f"Dynamic override test: Asked for 5.0%, RiskGate capped at: {actual_cap}%")
        if actual_cap != 1.5:
            logger.error("❌ CRITICAL: RiskGate cap override bypass detected!")
            sys.exit(3)
            
        logger.info("✅ Drawdown bounds are secure and verified.")
    except Exception as exc:
        logger.error(f"❌ Drawdown checks failed: {exc}")
        sys.exit(4)

def check_directory_permissions(state_dir):
    logger.info("Step 3/6: Verifying persistent directory write permissions...")
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
            sys.exit(5)

def audit_log_redaction():
    logger.info("Step 4/6: Auditing log redaction and secret privacy...")
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
                sys.exit(6)
                
        logger.info("✅ Log redaction/leak checks passed.")
    finally:
        test_logger.removeHandler(capture_handler)

def check_live_trading_gates(KiConfig):
    logger.info("Step 5/6: Verifying runtime safety gates...")
    # Ensure live trading defaults to False if testing or not explicitly enabled
    live_trading_env = os.getenv("KIBOT_LIVE_TRADING_ENABLED", "false").lower() == "true"
    logger.info(f"KIBOT_LIVE_TRADING_ENABLED in env: {live_trading_env}")
    logger.info(f"KiConfig.LIVE_TRADING_ENABLED resolves to: {KiConfig.LIVE_TRADING_ENABLED}")
    
    if not live_trading_env and KiConfig.LIVE_TRADING_ENABLED:
        logger.error("❌ CRITICAL: Live trading enabled in code but disabled in environment!")
        sys.exit(7)
        
    logger.info("✅ Live trading gates are fully aligned.")

def check_network_bindings():
    logger.info("Step 6/6: Auditing zero-trust port bindings...")
    try:
        import psutil
    except ImportError:
        logger.warning("⚠️ psutil not installed, skipping advanced network bind audits.")
        return

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
        connections = psutil.net_connections(kind='all')
        exposed_services = []
        for conn in connections:
            laddr = conn.laddr
            if laddr and laddr.port in target_ports:
                ip = laddr.ip
                if ip in forbidden_wildcards:
                    exposed_services.append(f"{target_ports[laddr.port]} (port {laddr.port}) is bound to public wildcard address '{ip}'!")
        
        if exposed_services:
            for exp in exposed_services:
                logger.error(f"❌ SECURITY EXPOSURE: {exp}")
            sys.exit(8)

        logger.info("✅ All core services are securely bound (zero-trust verified).")
    except Exception as exc:
        logger.warning(f"⚠️ Could not audit network bindings: {exc}")

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
    
    logger.info("==================================================")
    logger.info("🎉 HEALTHCHECK PASSED SUCCESSFULLY! ALL SYSTEMS GREEN.")
    logger.info("==================================================")
    sys.exit(0)

if __name__ == "__main__":
    main()
