import socket
import json
import time

NODES = {
    "SCANNER": {"ip": "152.69.218.198", "port": 9991},
    "EXECUTOR": {"ip": "213.35.118.26", "port": 9991}
}

def check_port(ip, port, timeout=3):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except:
        return False

def diagnose():
    print("🛰️ KiBot Trinity Mesh Diagnostics")
    print("="*40)
    
    for name, cfg in NODES.items():
        ip = cfg["ip"]
        port = cfg["port"]
        print(f"\nChecking node: {name} ({ip})")
        
        # Check SSH
        ssh_ok = check_port(ip, 22)
        print(f"  - SSH (22): {'🟢 ONLINE' if ssh_ok else '🔴 OFFLINE'}")
        
        # Check API Port
        api_ok = check_port(ip, port)
        print(f"  - API ({port}): {'🟢 ONLINE' if api_ok else '🔴 OFFLINE'}")
        
    print("\n" + "="*40)
    print("Diagnostics complete.")

if __name__ == "__main__":
    diagnose()
