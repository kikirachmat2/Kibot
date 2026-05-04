#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# Setup paths
root = Path(__file__).resolve().parent.parent
for d in ["Core_Logic", "Support", "Security"]:
    sys.path.append(str(root / d))

import ki_config
from sovereign_arbitrator import get_arbitrator, AllocationRequest
from kibot_sentinel import get_sentinel
import kibot_security

def test_vault_loading():
    print("\n--- [TEST] Vault Loading ---")
    # Check if a known key from .env is loaded in os.environ
    key = os.getenv("CEREBRAS_API_KEY")
    if key and not key.startswith("ENC("):
        print(f"[OK] CEREBRAS_API_KEY loaded and decrypted correctly.")
    else:
        print(f"[FAIL] CEREBRAS_API_KEY is: {key}")

def test_sentinel_killswitch():
    print("\n--- [TEST] Sentinel Kill-Switch ---")
    arbitrator = get_arbitrator()
    sentinel = get_sentinel()
    sentinel.reset()
    
    # Prime balances to bypass stale check
    arbitrator.update_balances(indodax_idr=100_000_000, polymarket_usdc=5000)
    print("Simulating 6 rapid trades...")
    req = AllocationRequest(source="INDODAX", asset="BTC/IDR", signal_score=0.9, ev_estimate=0.1)
    
    for i in range(6):
        approved, size, reason = arbitrator.request_allocation(req)
        if approved:
            print(f"  Trade {i+1}: Approved. Registering success...")
            # Simulate reporting result
            arbitrator.report_pnl(10000) 
        else:
            print(f"  Trade {i+1}: Blocked. Reason: {reason}")
            if "Velocity Breach" in reason or "SENTINEL VETO" in reason:
                print("[OK] Sentinel correctly blocked excessive trade velocity.")
                return

    print("[FAIL] Sentinel failed to block excessive trades.")

def test_log_integrity():
    print("\n--- [TEST] Log Integrity ---")
    kibot_security._append_log({"test": "data", "val": 123})
    violations = kibot_security.verify_logs()
    if not violations:
        print("[OK] Log signature verified.")
    else:
        print(f"[FAIL] Unexpected violations: {violations}")

    # Simulate tampering
    print("Simulating tampering...")
    log_file = root / "state" / "security_log.jsonl"
    lines = log_file.read_text().splitlines()
    if lines:
        import json
        last_entry = json.loads(lines[-1])
        last_entry["p"]["test"] = "TAMPERED"
        lines[-1] = json.dumps(last_entry)
        log_file.write_text("\n".join(lines) + "\n")
        
        violations = kibot_security.verify_logs()
        if any("Signature mismatch" in v for v in violations):
            print("[OK] Tampering detected successfully.")
        else:
            print("[FAIL] Tampering was NOT detected.")

if __name__ == "__main__":
    try:
        test_vault_loading()
        test_sentinel_killswitch()
        test_log_integrity()
    except Exception as e:
        print(f"Test Error: {e}")
        import traceback
        traceback.print_exc()
