#!/usr/bin/env python3
import time, json, os, subprocess, socket
from pathlib import Path

WEB_DIR = Path("/home/ubuntu/KiBot/web")
STATUS_FILE = WEB_DIR / "status.json"

NODES = {
    "BATAM": "127.0.0.1",
    "EXECUTOR": "213.35.118.26",
    "SCANNER": "152.69.218.198"
}

def check_port(host, port):
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except:
        return False

def get_cluster_status():
    status = {
        "ts": time.time(),
        "nodes": {
            "Batam (Brain)": {
                "ip": NODES["BATAM"],
                "manager": check_port("127.0.0.1", 9998),
                "proxy": check_port("127.0.0.1", 8787),
                "ollama": check_port("127.0.0.1", 11434)
            },
            "EXECUTOR (Executor)": {
                "ip": NODES["EXECUTOR"],
                "KiBot": check_port(NODES["EXECUTOR"], 8787),
                "polymarket": check_port(NODES["EXECUTOR"], 11600)
            },
            "SCANNER (Scanner)": {
                "ip": NODES["SCANNER"],
                "scanners_count": 15
            }
        }
    }
    return status

def run():
    print("[MONITOR] Starting cluster monitor loop...")
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        data = get_cluster_status()
        STATUS_FILE.write_text(json.dumps(data, indent=2))
        time.sleep(30)

if __name__ == "__main__":
    run()
