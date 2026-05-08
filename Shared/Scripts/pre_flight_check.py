#!/usr/bin/env python3
import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def check_file(path, required_text=None):
    p = ROOT / path
    if not p.exists():
        print(f"❌ MISSING: {path}")
        return False
    if required_text:
        content = p.read_text()
        if required_text not in content:
            print(f"❌ INVALID: {path} (missing '{required_text}')")
            return False
    print(f"✅ OK: {path}")
    return True

def main():
    print("=== KiBot Trinity Pre-Flight Audit ===")
    
    # 1. Critical Files
    critical = [
        ("SERVER_BATAM/Core_Logic/kibot_manager.py", "_strategy_learning_loop"),
        ("SERVER_BATAM/Core_Logic/kibot_manager.py", "_state_server_loop"),
        ("SERVER_BATAM/Core_Logic/kibot_manager.py", "run_local_signal_engine_manager"),
        ("SERVER_BATAM/Infrastructure/Infra/systemd/kibot-trinity.service", "MemoryMax=1500M"),
        ("SERVER_BATAM/Infrastructure/Infra/systemd/kibot-trinity.service", "CPUQuota=80%"),
        ("SERVER_BATAM/Indicators_Math/kibot_polymarket.py", "PAPER_TRADE_CAPITAL_USD"),
    ]
    
    all_ok = True
    for path, text in critical:
        if not check_file(path, text):
            all_ok = False
            
    # 2. Environment (Local Presence)
    env_files = [".env.server", ".env.kibot", ".env.kibot_manager"]
    for f in env_files:
        if not (ROOT / f).exists():
            print(f"⚠️  WARNING: {f} missing locally (ensure it exists on server)")

    if all_ok:
        print("\n🚀 ALL CRITICAL HARDENING VERIFIED. READY FOR DEPLOYMENT.")
        sys.exit(0)
    else:
        print("\n🛑 AUDIT FAILED. DO NOT DEPLOY.")
        sys.exit(1)

if __name__ == "__main__":
    main()
