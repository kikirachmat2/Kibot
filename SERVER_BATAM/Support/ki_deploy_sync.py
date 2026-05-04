#!/usr/bin/env python3
import subprocess
import os
from pathlib import Path

# --- CONFIGURATION ---
BASE_DIR = Path(__file__).resolve().parent.parent
SSH_DIR = BASE_DIR / "Infrastructure" / "SSH"

NODES = {
    "BATAM_MANAGER": {
        "host": "100.103.77.10",
        "user": "ubuntu",
        "key": SSH_DIR / "ssh-key-batam-active.pem",
        "dest": "/home/ubuntu/KiBot/Batam/"
    },
    "SINGAPORE_EXECUTOR": {
        "host": "100.122.1.109",
        "user": "ubuntu",
        "key": SSH_DIR / "ssh-key-executor.pem",
        "dest": "/home/ubuntu/KiBot/Batam/"
    },
    "SINGAPORE_SCANNER": {
        "host": "100.105.139.21",
        "user": "ubuntu",
        "key": SSH_DIR / "ssh-key-scanner.pem",
        "dest": "/home/ubuntu/KiBot/Batam/"
    }
}

EXCLUDE = [
    ".git", "__pycache__", "logs", "state", ".env", "*.pyc", ".DS_Store", "scratch"
]

def sync_node(name, config, dry_run=False):
    print(f"🚀 Syncing {name} ({config['host']})...")
    
    exclude_args = [f"--exclude={item}" for item in EXCLUDE]
    
    # Construct rsync command
    # -a: archive, -v: verbose, -z: compress, -e: ssh command
    cmd = [
        "rsync", "-avz",
        "-e", f"ssh -i '{config['key']}' -o StrictHostKeyChecking=no",
        str(BASE_DIR) + "/", # Source must end with / to sync contents
        f"{config['user']}@{config['host']}:{config['dest']}"
    ] + exclude_args
    
    if dry_run:
        cmd.append("--dry-run")
        print("🔍 [DRY RUN] Command:", " ".join(cmd))
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ {name} sync success!")
        else:
            print(f"❌ {name} sync failed: {result.stderr}")
    except Exception as e:
        print(f"❌ {name} error: {e}")

def main():
    import sys
    dry_run = "--dry-run" in sys.argv
    
    print(f"--- KiBot Cluster Sync (Source: {BASE_DIR}) ---")
    if dry_run:
        print("⚠️  DRY RUN MODE ENABLED")
        
    for name, config in NODES.items():
        sync_node(name, config, dry_run)
    
    print("\nDone. Don't forget to restart services if needed: 'python3 Support/ki_cluster_ctl.py restart all'")

if __name__ == "__main__":
    main()
