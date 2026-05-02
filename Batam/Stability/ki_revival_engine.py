#!/usr/bin/env python3
"""
KiBot Trinity Sovereign Watchdog (Lazarus Engine)
================================================
Autonomous diagnostic and auto-remediation framework.
Ensures 24/7 operation of core trading and research systems.
"""

import os
import json
import time
import subprocess
import socket
from pathlib import Path
from typing import Dict, List, Any

# Dynamic Root Resolution
ROOT_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT_DIR / "state"
LOGS_DIR = ROOT_DIR / "logs"

STATE_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

class LazarusEngine:
    def __init__(self):
        self.diagnostic_file = STATE_DIR / "lazarus_diagnostic.json"
        self.telegram_enabled = os.getenv("KIBOT_ENABLE_TELEGRAM", "true").lower() == "true"
        
    def _log(self, msg: str):
        print(f"[LAZARUS][{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

    def check_connectivity(self) -> bool:
        """Check if internet is accessible (pings Google DNS)."""
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except OSError:
            return False

    def is_process_running(self, script_name: str) -> bool:
        """Check if a python script is currently running."""
        try:
            output = subprocess.check_output(["pgrep", "-f", script_name]).decode()
            return len(output.strip()) > 0
        except:
            return False

    def check_and_revive(self):
        self._log("Initiating system-wide diagnostic...")
        
        status = {
            "ts": time.time(),
            "internet": self.check_connectivity(),
            "services": {}
        }

        # 1. Check Internet
        if not status["internet"]:
            self._log("[CRITICAL] Internet connectivity lost. Waiting for recovery...")
            return

        # 2. Check Core Services
        core_services = {
            "ki_brain.py": str(ROOT_DIR / "Core_Logic" / "ki_brain.py"),
            "kibot_ai_coordinator.py": str(ROOT_DIR / "AI_Orchestration" / "kibot_ai_coordinator.py"),
        }

        for name, path in core_services.items():
            running = self.is_process_running(name)
            status["services"][name] = {"running": running}
            
            if not running:
                self._log(f"[WARN] {name} is NOT running. Attempting revival...")
                try:
                    # Run in background
                    subprocess.Popen(["python3", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self._log(f"[OK] {name} revival signal sent.")
                except Exception as e:
                    self._log(f"[ERR] Failed to revive {name}: {e}")
            else:
                self._log(f"[HEALTH] {name} is active.")

        # 2.5 Trigger AI World Scout (Proactive Research)
        scout_name = "kibot_ai_scout.py"
        if not self.is_process_running(scout_name):
            self._log(f"[WARN] {scout_name} is NOT running. Attempting revival...")
            try:
                scout_path = ROOT_DIR / "AI_Orchestration" / scout_name
                subprocess.Popen(["python3", str(scout_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._log(f"[OK] {scout_name} revival signal sent.")
            except Exception as e:
                self._log(f"[ERR] Failed to trigger World Scout: {e}")
        else:
            self._log(f"[HEALTH] {scout_name} is active.")

        # 3. Clean Stale Locks
        for lock in STATE_DIR.glob("*.lock"):
            age = time.time() - lock.stat().st_mtime
            if age > 600: # 10 minutes stale
                self._log(f"[CLEANUP] Removing stale lock: {lock.name}")
                lock.unlink()

        # 4. Save Status
        try:
            self.diagnostic_file.write_text(json.dumps(status, indent=2))
        except: pass

    def run_loop(self):
        self._log("Lazarus Sovereign Watchdog Online. Monitoring 24/7.")
        while True:
            try:
                self.check_and_revive()
            except Exception as e:
                self._log(f"[FATAL] Watchdog error: {e}")
            time.sleep(300) # Patrol every 5 minutes as requested

if __name__ == "__main__":
    # Ensure .env is loaded for revival
    dotenv_path = ROOT_DIR / ".env"
    if dotenv_path.exists():
        for line in dotenv_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip("'").strip('"')
                
    LazarusEngine().run_loop()
