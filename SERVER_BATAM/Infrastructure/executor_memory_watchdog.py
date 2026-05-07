import os
import psutil
import subprocess

THRESHOLD_MB = 100
EXECUTOR_SERVICE = os.getenv("KIBOT_EXECUTOR_SERVICE", "kibot-executor-engine.service")

def get_available_memory():
    return psutil.virtual_memory().available / (1024 * 1024)

def check_memory():
    available = get_available_memory()
    print(f"Available memory: {available:.2f} MB")

    if available < THRESHOLD_MB:
        print(f"Memory low (< {THRESHOLD_MB} MB). Restarting critical services...")
        # Restart Java Engine if RAM is dangerously low
        subprocess.run(["systemctl", "restart", EXECUTOR_SERVICE], check=False)
        print(f"{EXECUTOR_SERVICE} restarted.")

if __name__ == "__main__":
    check_memory()
