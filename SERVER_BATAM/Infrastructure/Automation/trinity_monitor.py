#!/usr/bin/env python3
import time
import os
import sys
from pathlib import Path
import subprocess
import socket

# Ensure Support is in sys.path to import ki_utils
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(ROOT / "Support"))

from ki_utils import telegram_send

NODES = {
    "SCANNER": "152.69.218.198",
    "EXECUTOR": "213.35.118.26"
}

def check_ping(host: str) -> bool:
    try:
        # Ping with 1 count, 2 seconds timeout
        res = subprocess.run(["ping", "-c", "1", "-W", "2", host], capture_output=True)
        return res.returncode == 0
    except Exception:
        return False

def run_monitor():
    telegram_send("🚀 Trinity Monitor Started. Watching Scanner & Executor 24/7.")
    offline_nodes = set()

    while True:
        for node_name, ip in NODES.items():
            is_online = check_ping(ip)
            
            if not is_online:
                if node_name not in offline_nodes:
                    offline_nodes.add(node_name)
                    telegram_send(f"🚨 CRITICAL: Node {node_name} ({ip}) is UNREACHABLE! Please investigate immediately.")
            else:
                if node_name in offline_nodes:
                    offline_nodes.remove(node_name)
                    telegram_send(f"✅ RECOVERY: Node {node_name} ({ip}) is back ONLINE.")
        
        time.sleep(60) # Check every 60 seconds

if __name__ == "__main__":
    run_monitor()
