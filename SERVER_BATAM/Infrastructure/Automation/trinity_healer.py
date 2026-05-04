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
# UPGRADED TO DEEPSEEK 16B FOR MAXIMUM ACCURACY
OLLAMA_MODEL = "ollama/deepseek-coder-v2:16b" 
BASE_DIR = "/home/ubuntu/KiBot/SERVER_BATAM"

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
    logs = get_last_logs(service)
    
    # Advanced Prompting for DeepSeek
    prompt = f"""
    CONTEXT: You are the Autonomous Healer for KiBot Trinity.
    ISSUE: The service {service} has crashed.
    LOGS:
    {logs}
    
    TASK:
    1. Analyze the logs to find the root cause (e.g., FileNotFoundError, ConnectionError, SyntaxError).
    2. Scan the relevant files in {BASE_DIR}.
    3. FIX the code to prevent this crash from happening again.
    4. If it's a missing directory or environment issue, fix it.
    
    Apply the changes and explain what you did.
    """
    
    env = os.environ.copy()
    env["OLLAMA_API_BASE"] = "http://localhost:11434"
    
    aider_args = [
        AIDER_CMD,
        "--model", OLLAMA_MODEL,
        "--message", prompt,
        "--yes",        # Auto-apply changes
        "--no-git",     # We manage git centrally from Batam
        "--subtree-only" # Stay in KiBot directory
    ]
    
    try:
        log_event(f"🤖 DeepSeek-Coder-V2 is analyzing {service}...")
        subprocess.run(aider_args, cwd=BASE_DIR, env=env, check=True)
        log_event(f"✨ Healing complete. Restarting {service}...")
        subprocess.run(f"sudo systemctl restart {service}", shell=True)
        
        # Verify fix
        time.sleep(2)
        if get_service_status(service):
            log_event(f"✅ SUCCESS: {service} is now ACTIVE.")
        else:
            log_event(f"❌ FAILED: {service} still down after healing.")
            
    except Exception as e:
        log_event(f"❌ ERROR during healing process: {str(e)}")

def main():
    log_event("🚀 KiBot Trinity Autonomous Healer v1.1 (DeepSeek Edition) Started")
    while True:
        for service in TARGET_SERVICES:
            if not get_service_status(service):
                heal_service(service)
        time.sleep(15) # Faster check intervals

if __name__ == "__main__":
    main()
