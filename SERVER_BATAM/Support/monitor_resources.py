#!/usr/bin/env python3
import psutil
import json
import time
import os
import requests
from datetime import datetime
from pathlib import Path

# Thresholds
CPU_THRESHOLD = 85.0
RAM_THRESHOLD = 85.0
DISK_THRESHOLD = 90.0

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "state"
LOG_FILE = STATE_DIR / "resource_usage.json"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Telegram Config (Loaded from env or ki_config defaults)
# We try to import ki_config if possible, else use env
try:
    import sys
    sys.path.append(str(BASE_DIR / "Support"))
    from ki_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
except ImportError:
    TELEGRAM_BOT_TOKEN = os.getenv("KIBOT_TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("KIBOT_TELEGRAM_CHAT_ID")

def send_telegram(message: str):
    # SILENCED: User requested to stop spam
    print(f"[MONITOR][MUTE] Alert suppressed: {message}")
    return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": f"⚠️ [KiBot Batam] RESOURCE ALERT\n\n{message}", "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[MONITOR] Failed to send telegram: {e}")

def get_resources():
    cpu_pct = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    return {
        "timestamp": datetime.now().isoformat(),
        "cpu_pct": cpu_pct,
        "ram_pct": ram.percent,
        "ram_used_gb": round(ram.used / (1024**3), 2),
        "ram_total_gb": round(ram.total / (1024**3), 2),
        "disk_pct": disk.percent,
        "disk_used_gb": round(disk.used / (1024**3), 2),
        "disk_total_gb": round(disk.total / (1024**3), 2),
    }

def main():
    stats = get_resources()
    print(f"[MONITOR] CPU: {stats['cpu_pct']}% | RAM: {stats['ram_pct']}% | Disk: {stats['disk_pct']}%")
    
    # Check thresholds
    alerts = []
    if stats['cpu_pct'] > CPU_THRESHOLD:
        alerts.append(f"🔴 CPU Usage High: {stats['cpu_pct']}%")
    if stats['ram_pct'] > RAM_THRESHOLD:
        alerts.append(f"🔴 RAM Usage High: {stats['ram_pct']}% ({stats['ram_used_gb']}GB / {stats['ram_total_gb']}GB)")
    if stats['disk_pct'] > DISK_THRESHOLD:
        alerts.append(f"🔴 Disk Usage High: {stats['disk_pct']}%")
    
    if alerts:
        send_telegram("\n".join(alerts))
    
    # Save to log (keep last 100 entries)
    history = []
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, 'r') as f:
                history = json.load(f)
        except:
            history = []
            
    history.append(stats)
    history = history[-100:] # Keep recent history
    
    with open(LOG_FILE, 'w') as f:
        json.dump(history, f, indent=2)

if __name__ == "__main__":
    main()
