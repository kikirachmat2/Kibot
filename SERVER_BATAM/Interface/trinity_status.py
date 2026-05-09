# ==============================================================================
# KiBot Trinity: Unified Status Dashboard
# Role: One View to Rule the Mesh
# ==============================================================================

import os
import sys
import requests
import json
from datetime import datetime

# Add paths to imports (Robust Path Resolution)
import sys
from pathlib import Path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

# Standard imports
try:
    from SERVER_BATAM.Support.ki_config import KiConfig
except ImportError:
    from Support.ki_config import KiConfig

def check_node(name, ip, port=9991):
    try:
        # Simple health check via command plane API
        response = requests.get(f"http://{ip}:{port}/status", timeout=2)
        if response.status_code == 200:
            return "✅ ONLINE", response.json().get('uptime', 'N/A')
    except:
        return "❌ OFFLINE", "N/A"

def show_dashboard():
    print("="*60)
    print(f"🛡️  KiBot Trinity Sovereign Dashboard | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Philosophy: {KiConfig.PHILOSOPHY}")
    print("="*60)
    
    nodes = [
        ("BATAM (Master)", "127.0.0.1"),
        ("SCANNER (Tokyo)", KiConfig.SCANNER_NODE),
        ("EXECUTOR (SG)", KiConfig.EXECUTOR_NODE)
    ]
    
    print(f"{'NODE NAME':<20} | {'STATUS':<10} | {'UPTIME/MSG':<15}")
    print("-" * 60)
    
    for name, ip in nodes:
        status, uptime = check_node(name, ip)
        print(f"{name:<20} | {status:<10} | {uptime:<15}")
    
    print("-" * 60)
    print(f"💰 Daily Limit: -{KiConfig.MAX_DAILY_LOSS_PERCENT}% | 🎯 Min Prob: {KiConfig.MIN_SIGNAL_PROBABILITY*100}%")
    print("="*60)

if __name__ == "__main__":
    show_dashboard()
