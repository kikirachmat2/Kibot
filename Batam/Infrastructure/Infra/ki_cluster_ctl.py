#!/usr/bin/env python3
import subprocess, os, sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
KEYS = {
    "BATAM": os.path.join(ROOT_DIR, "SSH_BATAM/ssh-key-batam-active.pem"),
    "EXECUTOR": os.path.join(ROOT_DIR, "SSH_SINGAPORE/SSH_EXECUTOR/ssh-key-2026-03-22.key"),
    "SCANNER": os.path.join(ROOT_DIR, "SSH_SINGAPORE/SSH_SCANNER/ssh-key-2026-03-27.key")
}
IPS = {
    "BATAM": "168.110.201.228",
    "EXECUTOR": "213.35.118.26",
    "SCANNER": "152.69.218.198"
}

def run_remote(node, cmd):
    if node not in KEYS: return False, "Invalid node"
    ssh_cmd = [
        "ssh", "-i", KEYS[node], 
        "-o", "StrictHostKeyChecking=no",
        f"ubuntu@{IPS[node]}", cmd
    ]
    try:
        res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
        return res.returncode == 0, res.stdout + res.stderr
    except Exception as e:
        return False, str(e)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: ki_cluster_ctl.py [EXECUTOR|SCANNER] [command]")
        sys.exit(1)
    ok, out = run_remote(sys.argv[1], sys.argv[2])
    print(out)
    sys.exit(0 if ok else 1)
