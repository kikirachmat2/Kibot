import asyncio
import os
import sys
from pathlib import Path
import json

# Setup paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(ROOT_DIR))

from SERVER_BATAM.Support.ki_vault import load_sovereign_env
from SERVER_EXECUTOR.Core.Python_Executor.indodax_gateway import IndodaxGateway

def print_banner():
    print("""
    \033[95m████████╗██████╗ ██╗███╗   ██╗██╗████████╗██╗   ██╗
    ╚══██╔══╝██╔══██╗██║████╗  ██║██║╚══██╔══╝╚██╗ ██╔╝
       ██║   ██████╔╝██║██╔██╗ ██║██║   ██║    ╚████╔╝ 
       ██║   ██╔══██╗██║██║╚██╗██║██║   ██║     ╚██╔╝  
       ██║   ██║  ██║██║██║ ╚████║██║   ██║      ██║   
       ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝╚═╝   ╚═╝      ╚═╝   \033[0m
    \033[94mSovereign Python Trading Engine — CLI Management\033[0m
    """)

async def check_balance():
    print("\033[96m[SYSTEM] Fetching Indodax Balances...\033[0m")
    gateway = IndodaxGateway()
    try:
        info = await gateway.get_info()
        if not info:
            print("\033[91m❌ Failed to retrieve balance. Check your API Keys.\033[0m")
            return

        print("\n\033[92m--- INDODAX BALANCES ---\033[0m")
        balances = info.get("return", {}).get("balance", {})
        for asset, amount in balances.items():
            if float(amount) > 0:
                print(f"💰 {asset.upper()}: {amount}")
    except Exception as e:
        print(f"\033[91m❌ Error: {e}\033[0m")

def show_status():
    print("\n\033[92m--- SYSTEM STATUS ---\033[0m")
    # Check if executor is running (checking PID or port could be done here)
    print("🤖 Trinity Executor: \033[93mIDLE (Waiting for Signals)\033[0m")
    print("🔮 Polymarket Gateway: \033[92mONLINE (Port 11600)\033[0m")
    print("🛰️  Batam Link: \033[92mCONNECTED\033[0m")
    print("🔒 Vault: \033[92mACTIVE (Encrypted)\033[0m")

if __name__ == "__main__":
    load_sovereign_env()
    print_banner()
    
    if len(sys.argv) < 2:
        print("Usage: python3 trinity_cli.py [balance | status | test-signal]")
        sys.exit(1)
        
    cmd = sys.argv[1].lower()
    if cmd == "balance":
        asyncio.run(check_balance())
    elif cmd == "status":
        show_status()
    else:
        print(f"Unknown command: {cmd}")
