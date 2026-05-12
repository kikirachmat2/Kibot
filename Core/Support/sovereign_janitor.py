#!/usr/bin/env python3
import os
import shutil
import subprocess
import time
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] 🧹 JANITOR - %(levelname)s - %(message)s')
logger = logging.getLogger("SovereignJanitor")

class SovereignJanitor:
    def __init__(self, threshold_pct=90.0):
        from Core.Support.ki_config import LOGS_DIR
        self.threshold = threshold_pct
        self.log_paths = [
            LOGS_DIR,
            Path("/var/log/journal")
        ]

    def check_disk_space(self):
        total, used, free = shutil.disk_usage("/")
        usage_pct = (used / total) * 100
        logger.info(f"Disk Usage: {usage_pct:.2f}%")
        
        if usage_pct > self.threshold:
            logger.warning("🚨 CRITICAL DISK USAGE! Initiating emergency cleanup...")
            self.cleanup_logs()

    def cleanup_logs(self):
        """Purge old log files and vacuum journalctl."""
        try:
            # Prefer the wider disk cleaner first so nested repo / cache regressions
            # are handled by the same guardrail that fixed the original outage.
            try:
                from Core.sovereign_disk_cleaner import run_cleanup
                run_cleanup(dry_run=False)
                return
            except Exception as cleaner_error:
                logger.warning(f"Disk cleaner unavailable, falling back to log-only cleanup: {cleaner_error}")

            # Fallback: vacuum journal + clear large application logs.
            subprocess.run(["sudo", "journalctl", "--vacuum-size=500M"], check=True)
            for p in self.log_paths:
                if p.exists():
                    for f in p.glob("*.log"):
                        if f.stat().st_size > 50 * 1024 * 1024: # > 50MB
                            with open(f, 'w') as log_file:
                                log_file.truncate(0)
                            logger.info(f"Truncated large log: {f.name}")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")

    def check_ollama_health(self):
        """Ping local Ollama to ensure it's responding."""
        try:
            result = subprocess.run(
                ["curl", "-s", "http://localhost:11434/api/tags"],
                capture_output=True, timeout=5
            )
            if result.returncode != 0:
                raise Exception("Ollama not responding")
        except Exception:
            logger.warning("🚨 OLLAMA DOWN! Attempting self-healing restart...")
            subprocess.run(["sudo", "systemctl", "restart", "ollama"], check=False)

    def run_forever(self):
        logger.info("🛡️ Sovereign Janitor Active. Watching your infrastructure...")
        while True:
            self.check_disk_space()
            self.check_ollama_health()
            # Check every 15 minutes
            time.sleep(900)

if __name__ == "__main__":
    janitor = SovereignJanitor()
    janitor.run_forever()
