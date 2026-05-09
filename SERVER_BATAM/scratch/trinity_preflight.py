import subprocess
import os
import sys

# Simulation of KiBot Master Remote Logic
NODES = {
    "SCANNER": {"ip": "100.117.152.88"}, # Singapore Scanner
    "EXECUTOR": {"ip": "100.82.44.116"}   # Singapore Executor
}

def test_remote_connectivity():
    print("🔍 Testing Trinity Mesh Connectivity...")
    for name, data in NODES.items():
        ip = data['ip']
        print(f"--- Testing {name} ({ip}) ---")
        
        # 1. Ping
        res = subprocess.run(["ping", "-c", "1", "-W", "2", ip], capture_output=True)
        print(f"📡 Ping: {'✅ OK' if res.returncode == 0 else '❌ FAILED'}")
        
        # 2. SSH & Stats
        cmd = ["ssh", "-o", "ConnectTimeout=5", ip, "uptime"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        print(f"🔑 SSH Handshake: {'✅ OK' if res.returncode == 0 else '❌ FAILED'}")
        if res.returncode == 0:
            print(f"📊 Remote Uptime: {res.stdout.strip()}")

def test_local_mechanic():
    print("\n🛠️ Testing Local Mechanic (Aider)...")
    aider_path = "/home/ubuntu/.local/bin/aider"
    if os.path.exists(aider_path) or subprocess.run(["which", "aider"], capture_output=True).returncode == 0:
        print("🤖 Aider: ✅ FOUND")
    else:
        print("🤖 Aider: ❌ NOT FOUND (Check path!)")

if __name__ == "__main__":
    # Note: This runs on Batam
    try:
        test_remote_connectivity()
        test_local_mechanic()
    except Exception as e:
        print(f"💥 Test Error: {e}")
