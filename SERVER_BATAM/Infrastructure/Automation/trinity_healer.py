import os
import subprocess
import time
from datetime import datetime

# CONFIGURATION - TRINITY APEX
TARGET_SERVICES = [
    "kibot-orchestrator.service",
    "kibot-trinity-governor.service",
    "kibot-security.service",
    "indodax-dashboard-proxy.service"
]

AIDER_CMD = "/home/ubuntu/.local/bin/aider"
OLLAMA_MODEL = "ollama/deepseek-coder-v2:16b" 
BASE_DIR = "/home/ubuntu/KiBot/SERVER_BATAM"
LOCK_FILE = "/tmp/kibot_healing.lock"

def log_event(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_file = os.path.join(BASE_DIR, "healer_activity.log")
    with open(log_file, "a") as f:
        f.write(f"[{timestamp}] {message}\n")
    print(f"[{timestamp}] {message}")

def get_service_status(service):
    cmd = f"systemctl is-active {service}"
    try:
        status = subprocess.check_output(cmd, shell=True).decode().strip()
        return status == "active"
    except:
        return False

def get_last_logs(service, lines=30):
    cmd = f"journalctl -u {service} -n {lines} --no-pager"
    return subprocess.check_output(cmd, shell=True).decode()

def heal_service(service):
    log_event(f"🚨 CRITICAL: Service {service} is DOWN. Initiating DeepSeek-Coder-V2 Healing...")
    
    # SET LOCK for Governor
    with open(LOCK_FILE, "w") as f:
        f.write(f"Healing {service} since {datetime.now()}")
    
    logs = get_last_logs(service)
    
    prompt = f"""
    CONTEXT: Autonomous Healer for KiBot Trinity.
    ISSUE: {service} crashed.
    LOGS:
    {logs}
    
    TASK: Find the bug in {BASE_DIR} and FIX it. Apply changes immediately.
    """
    
    env = os.environ.copy()
    env["OLLAMA_API_BASE"] = os.getenv("KIBOT_OLLAMA_API_BASE", os.getenv("OLLAMA_API_BASE", "http://127.0.0.1:11435"))
    
    aider_args = [
        AIDER_CMD, "--model", OLLAMA_MODEL, "--message", prompt,
        "--yes", "--no-git", "--subtree-only"
    ]
    
    try:
        log_event(f"🤖 DeepSeek is working on {service}...")
        subprocess.run(aider_args, cwd=BASE_DIR, env=env, check=True)
        log_event(f"✨ Healing complete. Restarting {service}...")
        subprocess.run(f"sudo systemctl restart {service}", shell=True)
        time.sleep(3)
    except Exception as e:
        log_event(f"❌ ERROR: {str(e)}")
    finally:
        # RELEASE LOCK
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            log_event(f"🔓 Lock released for Governor.")

def main():
    log_event("🚀 KiBot Trinity Autonomous Healer v1.2 (Sync Edition) Started")
    if os.path.exists(LOCK_FILE): os.remove(LOCK_FILE) # Reset on start
    while True:
        for service in TARGET_SERVICES:
            if not get_service_status(service):
                heal_service(service)
        time.sleep(10)

if __name__ == "__main__":
    main()
