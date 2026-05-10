#!/usr/bin/env python3
import time
import os
import sys
import threading
import subprocess
import re
import shlex
import shutil
import requests
from datetime import datetime
from pathlib import Path

# Ensure Support is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR / "Support"))

from ki_utils import telegram_send
from ki_config import OLLAMA_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# CONFIGURATION
LOGS_TO_WATCH = {
    "MASTER": "/home/ubuntu/KiBot/Batam/Logs/kibot_master.log",
    "ORCHESTRATOR": "/home/ubuntu/KiBot/Batam/Logs/orchestrator.log",
}

SAFE_COMMAND_PATTERNS = [
    r'^systemctl (status|is-active|restart|start|stop) kibot-\w+(\.service)?$',
    r'^systemctl (status|is-active|restart|start|stop) lazarus-ampere(\.service)?$',
    r'^find /home/ubuntu/KiBot/logs/ -name ".*\.log" -mtime \+\d+ -delete$',
    r'^sudo sync && echo 3 \| sudo tee /proc/sys/vm/drop_caches$',
    r'^df -h .*$',
    r'^free -h$',
    r'^uptime$'
]

def is_command_safe(cmd: str) -> bool:
    if cmd == 'sudo sync && echo 3 | sudo tee /proc/sys/vm/drop_caches':
        return True
    for pattern in SAFE_COMMAND_PATTERNS:
        if re.match(pattern, cmd):
            return True
    return False

def ask_ollama(prompt):
    try:
        payload = {'model': 'qwen3-coder:7b', 'messages': [{'role': 'user', 'content': prompt}], 'stream': False}
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=30)
        return r.json()['message']['content'].strip()
    except Exception as e:
        print(f"[TRINITY][OLLAMA][ERROR] {e}", flush=True)
        return None

def deploy_and_verify(name, fix_cmd):
    if not is_command_safe(fix_cmd):
        telegram_send(f"⚠️ *SECURITY BLOCK*\nTrinity attempted unsafe command:\n`{fix_cmd}`\n*BLOCKED*")
        return False
    try:
        if "|" in fix_cmd or "&&" in fix_cmd:
            subprocess.run(fix_cmd, shell=True, check=True)
        else:
            args = shlex.split(fix_cmd)
            subprocess.run(args, check=True)
        time.sleep(5)
        return True
    except Exception as e:
        print(f"[TRINITY][DEPLOY][ERROR] {e}", flush=True)
        return False

def tail_thread(name, path):
    print(f'[TRINITY] Watching {name}: {path}')
    try:
        proc = subprocess.Popen(['tail', '-n', '0', '-F', path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        while True:
            line = proc.stdout.readline().decode('utf-8')
            if not line: break
            if any(x in line for x in ['ERROR', 'CRITICAL', 'Exception', 'Traceback']):
                telegram_send(f"🔍 *LOG ALERT ({name})*:\n`{line.strip()}`")
    except Exception as e:
        print(f"[TRINITY][TAIL][ERROR] {name}: {e}", flush=True)

if __name__ == '__main__':
    time.sleep(10)
    telegram_send('🛡️ *TRINITY GOVERNOR v3.1 ACTIVE*\n(Secure Monitoring & Log Watch Enabled)')
    for name, path in LOGS_TO_WATCH.items():
        if os.path.exists(path):
            threading.Thread(target=tail_thread, args=(name, path), daemon=True).start()
    while True: time.sleep(1)
