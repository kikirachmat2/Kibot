import os
import subprocess
import time
import json

# CONFIGURATION
TARGET_SERVICES = [
    "kibot-orchestrator.service",
    "kibot-trinity-governor.service",
    "kibot-security.service",
    "indodax-dashboard-proxy.service"
]

AIDER_CMD = "/home/ubuntu/.local/bin/aider"
OLLAMA_MODEL = "ollama/qwen3:8b" # Using Qwen3 8b via Ollama
BASE_DIR = "/home/ubuntu/KiBot/SERVER_BATAM"

def get_service_status(service):
    cmd = f"systemctl is-active {service}"
    try:
        status = subprocess.check_output(cmd, shell=True).decode().strip()
        return status == "active"
    except:
        return False

def get_last_logs(service, lines=20):
    cmd = f"journalctl -u {service} -n {lines} --no-pager"
    return subprocess.check_output(cmd, shell=True).decode()

def heal_service(service):
    print(f"⚠️ Service {service} is down! Attempting Autonomous Healing...")
    logs = get_last_logs(service)
    
    # Create a prompt for Aider
    prompt = f"The service {service} is failing. Here are the last logs:\n\n{logs}\n\nPlease analyze the code in {BASE_DIR} and fix any bugs causing this failure. Focus on path issues, connection errors, or logic crashes."
    
    # Execute Aider with Ollama
    # Note: We use --yes to auto-apply changes
    env = os.environ.copy()
    env["OLLAMA_API_BASE"] = "http://localhost:11434"
    
    aider_args = [
        AIDER_CMD,
        "--model", OLLAMA_MODEL,
        "--message", prompt,
        "--yes",
        "--no-git"
    ]
    
    try:
        print(f"🤖 Calling Aider with {OLLAMA_MODEL}...")
        subprocess.run(aider_args, cwd=BASE_DIR, env=env, check=True)
        print(f"✅ Aider finished. Restarting {service}...")
        subprocess.run(f"sudo systemctl restart {service}", shell=True)
    except Exception as e:
        print(f"❌ Healing failed for {service}: {e}")

def main():
    print("🚀 KiBot Trinity Autonomous Healer Started")
    while True:
        for service in TARGET_SERVICES:
            if not get_service_status(service):
                heal_service(service)
        time.sleep(30) # Check every 30 seconds

if __name__ == "__main__":
    main()
