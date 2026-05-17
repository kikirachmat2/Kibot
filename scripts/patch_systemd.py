#!/usr/bin/env python3
import glob
import os
import shutil
import re

SERVICES = [
    "kibot-ai-scout",
    "kibot-dashboard",
    "kibot-executor-polymarket",
    "kibot-executor",
    "kibot-janitor",
    "kibot-master",
    "kibot-scanner",
]

def patch_services():
    print("Starting systemd security hardening patch...")
    for svc in SERVICES:
        path = f"/etc/systemd/system/{svc}.service"
        if not os.path.exists(path):
            print(f"⚠️ Service file not found: {path}")
            continue

        # 1. Create a backup
        backup_path = f"{path}.bak"
        shutil.copy2(path, backup_path)
        print(f"📦 Backed up {path} to {backup_path}")

        # 2. Read contents
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # 3. Patch TimeoutStopSec to 10
        if "TimeoutStopSec=" in content:
            content = re.sub(r"TimeoutStopSec=\d+", "TimeoutStopSec=10", content)
        else:
            # Inject under [Service] section
            content = content.replace("[Service]\n", "[Service]\nTimeoutStopSec=10\n")

        # 4. Inject ProtectHome=read-only
        if "ProtectHome=" in content:
            content = re.sub(r"ProtectHome=\S+", "ProtectHome=read-only", content)
        else:
            content = content.replace("[Service]\n", "[Service]\nProtectHome=read-only\n")

        # 5. Write back
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"✅ Hardened systemd service: {svc}")

if __name__ == "__main__":
    patch_services()
