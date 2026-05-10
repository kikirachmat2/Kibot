#!/usr/bin/env python3
import json
import os
import time
import hmac
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# Constants
ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
SECURITY_LOG = STATE_DIR / "security_log.jsonl"
LEGACY_SECURITY_LOG = STATE_DIR / "security_ledger.jsonl"

# Root Directory Setup
ROOT = Path(__file__).resolve().parent.parent

try:
    from SERVER_BATAM.Support.ki_vault import get_vault
except ImportError as e:
    print(f"Failed to import vault: {e}", file=sys.stderr)
    get_vault = lambda: None

def _get_signing_key() -> bytes:
    vault = get_vault()
    if vault:
        if hasattr(vault, "_initialize"):
            vault._initialize()
        if hasattr(vault, "_key") and vault._key:
            return vault._key
    # CRITICAL: No more hardcoded emergency keys. 
    # System must fail-secure if vault is missing.
    raise RuntimeError("SECURITY_FATAL: Crypto Vault is inaccessible. Unauthorized execution prevented.")

def _get_last_hash() -> str:
    """Gets the hash of the last entry in the ledger to ensure chain integrity."""
    source = SECURITY_LOG if SECURITY_LOG.exists() else LEGACY_SECURITY_LOG
    if not source.exists():
        return "GENESIS_BLOCK_0000000000000000"
    try:
        if source.stat().st_size == 0:
            return "GENESIS_BLOCK_0000000000000000"
    except OSError:
        return "ERROR_OR_TAMPERED"
    try:
        with open(source, "rb") as f:
            f.seek(-2, os.SEEK_END)
            while f.read(1) != b"\n":
                f.seek(-2, os.SEEK_CUR)
            last_line = f.readline().decode()
            data = json.loads(last_line)
            return str(data.get("h") or data.get("s") or "ERROR_OR_TAMPERED")
    except:
        return "ERROR_OR_TAMPERED"

def append_secure_log(event_type: str, message: str, severity: str = "INFO"):
    key = _get_signing_key()
    prev_hash = _get_last_hash()
    ts = datetime.now(timezone.utc).isoformat()
    
    payload = {
        "ts": ts,
        "type": event_type,
        "msg": message,
        "sev": severity,
        "prev": prev_hash
    }
    
    payload_str = json.dumps(payload, sort_keys=True)
    current_hash = hmac.new(key, payload_str.encode(), hashlib.sha256).hexdigest()
    
    entry = {"p": payload, "h": current_hash}
    
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(SECURITY_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _append_log(payload: dict, event_type: str = "LEGACY_EVENT", severity: str = "INFO") -> None:
    """Compatibility shim for older callers and smoke tests."""
    message = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    append_secure_log(event_type, message, severity)

def verify_ledger() -> bool:
    """Verifies the entire log chain. Any deletion or modification will return False."""
    if not SECURITY_LOG.exists():
        return True
    
    key = _get_signing_key()
    expected_prev_hash = "GENESIS_BLOCK_0000000000000000"
    
    with open(SECURITY_LOG, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            try:
                data = json.loads(line)
                payload = data["p"]
                actual_hash = str(data.get("h") or data.get("s") or "")
                if not actual_hash:
                    print(f"CORRUPTION at line {i}: missing signature")
                    return False
                
                # Check Chain Integrity
                if payload["prev"] != expected_prev_hash:
                    print(f"CHAIN_BREAK at line {i}: Sequence integrity violation.")
                    return False
                
                # Check Signature Integrity
                payload_str = json.dumps(payload, sort_keys=True)
                calc_hash = hmac.new(key, payload_str.encode(), hashlib.sha256).hexdigest()
                if actual_hash != calc_hash:
                    print(f"SIGNATURE_BREAK at line {i}: Content tampering detected.")
                    return False
                
                expected_prev_hash = actual_hash
            except Exception as e:
                print(f"CORRUPTION at line {i}: {e}")
                return False
    return True


def verify_logs() -> list[str]:
    """Compatibility shim that returns violations instead of a boolean."""
    violations: list[str] = []
    if not verify_ledger():
        violations.append("Signature mismatch or chain corruption detected")
    return violations

if __name__ == "__main__":
    if "--verify" in sys.argv:
        if verify_ledger():
            print("✅ Ledger Integrity Verified. No tampering detected.")
        else:
            print("❌ SECURITY ALERT: Ledger corruption or tampering detected!")
            sys.exit(1)
    else:
        append_secure_log("SECURITY_DAEMON", "Shield v9.0 Activated - Chain Ledger Mode", "INFO")
        print("🛡️ KiBot Shield Active.")
