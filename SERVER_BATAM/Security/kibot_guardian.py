import os
import time
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - GUARDIAN - %(message)s')

SERVICES = [
    "kibot-brain.service",
    "kibot-commander.service"
]

def check_service(service_name):
    """Cek apakah service atau proses aktif."""
    if service_name.endswith(".service"):
        res = subprocess.run(["sudo", "systemctl", "is-active", service_name], capture_output=True, text=True)
        return res.stdout.strip() == "active"
    else:
        # Untuk script python biasa
        res = subprocess.run(["pgrep", "-f", service_name], capture_output=True)
        return res.returncode == 0

def heal_service(service_name):
    """Membangkitkan service yang mati."""
    logging.warning(f"Healing {service_name}...")
    if service_name.endswith(".service"):
        os.system(f"sudo systemctl restart {service_name}")
    else:
        # Jalankan ulang script oracle
        os.system(f"nohup python3 /home/ubuntu/KiBot/SERVER_BATAM/Core_Logic/{service_name} > /dev/null 2>&1 &")

if __name__ == "__main__":
    while True:
        for s in SERVICES:
            if not check_service(s):
                heal_service(s)
            else:
                logging.info(f"{s} is Healthy.")
        time.sleep(30)
