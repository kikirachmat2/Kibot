import time, subprocess, json, os, requests, threading, re, shutil, sys, shlex
from pathlib import Path
from datetime import datetime

# --- CONFIGURATION ---
_base_path = Path(__file__).resolve().parent.parent
sys.path.append(str(_base_path / "Support"))
from ki_config import WIB, OLLAMA_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, BASE_PATH
from ki_utils import telegram_send, load_json, save_json

try:
    from kibot_learning_engine import get_engine
except ImportError:
    get_engine = None

REPO_PATH = str(BASE_PATH)
HEAL_HISTORY_FILE = Path(REPO_PATH) / 'state/trinity_heal_history.jsonl'

def report_to_github(action_type, details):
    """Autonomously report actions to GitHub repository with premium audit trail."""
    try:
        os.chdir(REPO_PATH)
        # 1. Ensure we are up to date
        subprocess.run(["git", "fetch", "origin"], check=False, capture_output=True)
        
        # 2. Add changes
        subprocess.run(
            [
                "git",
                "add",
                "-A",
                "--",
                ".",
                ":(exclude)**/.env",
                ":(exclude)**/.env.*",
                ":(exclude)**/*.pem",
                ":(exclude)**/*.key",
                ":(exclude)**/state",
                ":(exclude)**/logs",
                ":(exclude)**/__pycache__",
            ],
            check=False,
            capture_output=True,
        )
        
        # 3. Commit with rich metadata
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        commit_msg = f"🚀 [TRINITY-SOVEREIGN][{action_type}] {details}\n\nTimestamp: {timestamp}\nNode: Batam-Ampere-1"
        subprocess.run(["git", "commit", "-m", commit_msg], check=False, capture_output=True)
        
        # 4. Push (Retry once if failed)
        res = subprocess.run(["git", "push", "origin", "main"], check=False, capture_output=True)
        if res.returncode != 0:
            print("[TRINITY][GITHUB] Push failed, attempting rebase...", flush=True)
            subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=False, capture_output=True)
            subprocess.run(["git", "push", "origin", "main"], check=False, capture_output=True)
            
        print(f"[TRINITY][GITHUB] Action reported: {action_type}", flush=True)
    except Exception as e:
        print(f"[TRINITY][GITHUB][ERROR] {e}", flush=True)

def autonomous_git_watcher():
    """Checks for remote updates and applies them if safe."""
    while True:
        try:
            os.chdir(REPO_PATH)
            # Fetch without merging
            subprocess.run(["git", "fetch", "origin"], check=False)
            status = subprocess.check_output(["git", "status", "-uno"]).decode()
            
            if "behind" in status:
                print("[TRINITY][GIT] Update detected! Pulling and deploying...", flush=True)
                telegram_send("🔄 *TRINITY UPDATE*: New code detected on GitHub. Pulling and applying...")
                subprocess.run(["git", "pull", "origin", "main"], check=False)
                # Restart the primary runtime to apply changes
                subprocess.run(["systemctl", "restart", "kibot-trinity"], check=False)
                telegram_send("✅ *TRINITY UPDATE*: Code applied and Trinity restarted.")
        except Exception as e:
            print(f"[TRINITY][GIT][ERROR] {e}", flush=True)
        time.sleep(300) # Every 5 minutes

LOGS_TO_WATCH = {
    'MANAGER': os.path.join(REPO_PATH, 'logs/manager.log'),
    'EXECUTOR': os.path.join(REPO_PATH, 'logs/executor.log'),
    'SCANNER': os.path.join(REPO_PATH, 'logs/scanner.log')
}

import dynamic_config

def autonomous_tuning_loop():
    """Periodically adjusts parameters based on system health and win rate."""
    while True:
        try:
            # logic: analyze recent history (last 50 trades)
            # For now, simulate/read from a summary file if exists
            # We'll use a placeholder logic that checks for 'EXIT' frequency
            
            # Simple heuristic: If we had more than 3 losses in the last hour, tighten up.
            log_path = LOGS_TO_WATCH['MANAGER']
            if os.path.exists(log_path):
                # Read last 100 lines
                with open(log_path, 'r') as f:
                    lines = f.readlines()[-100:]
                
                losses = sum(1 for l in lines if 'pnl=Rp-' in l)
                wins = sum(1 for l in lines if 'pnl=Rp' in l and 'pnl=Rp-' not in l)
                
                total = wins + losses
                win_rate = wins / total if total > 0 else 0.5
                
                if total >= 5: # Only tune if we have enough sample
                    dynamic_config.sync_from_performance({"win_rate": win_rate})
                    
        except Exception as e:
            print(f"[TRINITY][TUNING][ERROR] {e}", flush=True)
        time.sleep(600) # Every 10 minutes

# --- SECURITY: SAFE COMMAND ALLOWLIST ---
# Only allow specific patterns. Use regex for flexibility but be strict.
SAFE_COMMAND_PATTERNS = [
    r'^systemctl (status|is-active|restart|start|stop) kibot-[\w-]+(\.service)?$',
    r'^systemctl (status|is-active|restart|start|stop) lazarus-ampere(\.service)?$',
    r'^find /home/ubuntu/KiBot/logs/ -name ".*\.log" -mtime \+\d+ -delete$',
    r'^sudo sync && echo 3 \| sudo tee /proc/sys/vm/drop_caches$',
    r'^df -h .*$',
    r'^free -h$',
    r'^uptime$'
]

def is_command_safe(cmd: str) -> bool:
    """Verifies if a command matches our security allowlist."""
    # Special case for the drop_caches pipe
    if cmd == 'sudo sync && echo 3 | sudo tee /proc/sys/vm/drop_caches':
        return True
    
    for pattern in SAFE_COMMAND_PATTERNS:
        if re.match(pattern, cmd):
            return True
    return False

def ask_ollama(prompt):
    try:
        payload = {'model': 'qwen2.5-coder:7b', 'messages': [{'role': 'user', 'content': prompt}], 'stream': False}
        r = requests.post(OLLAMA_URL, json=payload, timeout=30)
        return r.json()['message']['content'].strip()
    except Exception as e:
        print(f"[TRINITY][OLLAMA][ERROR] {e}", flush=True)
        return None

def ask_copilot(problem_desc, retry_info=''):
    try:
        prompt = f'suggest a one-line bash command to fix this: {problem_desc}. {retry_info}'
        # Using -p for direct output
        cmd_args = ["copilot", "-p", prompt]
        output = subprocess.check_output(cmd_args, stderr=subprocess.STDOUT).decode()
        for line in output.split('\n'):
            line = line.strip()
            if any(x in line for x in ['sudo', 'systemctl', 'rm ', 'mkdir', 'cp ', 'sed ']):
                return line
    except Exception as e:
        print(f"[TRINITY][COPILOT][ERROR] {e}", flush=True)
        return None

def deploy_and_verify(name, fix_cmd):
    if not is_command_safe(fix_cmd):
        telegram_send(f"⚠️ *SECURITY BLOCK*\nTrinity attempted unsafe command:\n`{fix_cmd}`\n*BLOCKED*")
        return False
        
    try:
        # Secure execution: if it's the drop_caches special case, use shell=True for the pipe
        if "|" in fix_cmd or "&&" in fix_cmd:
            subprocess.run(fix_cmd, shell=True, check=True)
        else:
            args = shlex.split(fix_cmd)
            subprocess.run(args, check=True)
            
        time.sleep(5)
        verify_cmd = ["systemctl", "is-active", f"kibot-{name.lower()}"]
        res = subprocess.run(verify_cmd, capture_output=True, text=True)
        return 'active' in res.stdout
    except Exception as e:
        print(f"[TRINITY][DEPLOY][ERROR] {e}", flush=True)
        return False

def trinity_pipeline(name, error_line):
    retries = 0
    retry_msg = ''
    while retries < 3:
        # 1. PELAJARI
        reason = ask_ollama(f'Analyze this error in {name}: {error_line}. {retry_msg}') or 'Analisa Gagal'
        
        # 2. PERBAIKI
        fix_cmd = ask_copilot(error_line, retry_msg) or ask_ollama(f'Fix for: {error_line}. One line bash command ONLY.')
        
        if fix_cmd:
            # 3. DEPLOY & KLARIFIKASI
            if deploy_and_verify(name, fix_cmd):
                telegram_send(f'✅ *TRINITY HEALED (Attempt {retries+1})*\n🔍 {name}\n🛠️ `{fix_cmd}`\n🚀 Status: NORMAL')
                report_to_github("HEAL", f"Fixed {name} with: {fix_cmd}")
                return
            else:
                retries += 1
                retry_msg = f'Last fix ({fix_cmd}) failed. Try a different approach.'
        else:
            retries += 1
            
    telegram_send(f'❌ *TRINITY FAILED*\n🔍 {name}\n⚠️ Error: {error_line}\nStatus: *Gagal setelah 3 kali percobaan.*')

def health_check_loop():
    engine = get_engine() if get_engine else None
    while True:
        try:
            # 1. Learning Patrol
            if engine:
                engine.patrol_and_audit()
                
            # 2. RAM Check
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()
                total = int(lines[0].split()[1])
                free = int(lines[1].split()[1])
                # Note: 'available' is often index 2
                available = int(lines[2].split()[1]) if len(lines) > 2 else free
                used_pct = ((total - available) / total) * 100
                
            if used_pct > 90.0:
                telegram_send(f'⚠️ *SYSTEM ALERT*: RAM Usage {used_pct:.1f}%. Optimizing...')
                subprocess.run('sudo sync && echo 3 | sudo tee /proc/sys/vm/drop_caches', shell=True)
            
            # Disk Check
            usage = shutil.disk_usage('/')
            percent = (usage.used / usage.total) * 100
            if percent > 90.0:
                telegram_send(f'⚠️ *SYSTEM ALERT*: Disk Usage {percent:.1f}%. Cleaning logs...')
                # Secure log cleaning
                log_clean_cmd = f'find {REPO_PATH}/logs/ -name "*.log" -mtime +7 -delete'
                if is_command_safe(log_clean_cmd):
                    subprocess.run(log_clean_cmd, shell=True)
                
        except Exception as e:
            print(f"[TRINITY][HEALTH][ERROR] {e}", flush=True)
        time.sleep(300)

def midnight_evolution():
    while True:
        now = datetime.now()
        if now.hour == 0 and now.minute == 0:
            telegram_send('🌙 *MIDNIGHT EVOLUTION INITIATED*')
            idea = ask_copilot('research online for new HFT trading features or server optimizations for a Python bot on OCI Ampere. suggest one actionable improvement.')
            if idea:
                telegram_send(f'💡 *EVOLUTION IDEA*:\n{idea}')
            time.sleep(60)
        time.sleep(30)

def perform_trade_autopsy(name, line):
    engine = get_engine() if get_engine else None
    if not engine: return
    
    match = re.search(r'EXIT\s+(\w+)\s+pnl=Rp(-\d+)\s+\(([-\d.]+)%\)', line)
    if match:
        pair = match.group(1)
        pnl_pct = match.group(3)
        reason = "Unknown"
        if "reason=" in line: reason = line.split("reason=")[1].split()[0]
        
        prompt = f"Analyze this trading loss for {pair}. PnL: {pnl_pct}%. Reason: {reason}. Context: {line}. Why did it lose and what is the lesson? Answer in 1 short sentence."
        lesson = ask_ollama(prompt)
        if lesson:
            telegram_send(f"🔬 *AI AUTOPSY ({pair})*:\n{lesson}")
            try:
                stats = engine.get_stats(pair)
                stats.lessons.append(f"{datetime.now().strftime('%Y-%m-%d')}: {lesson}")
                engine.save_stats(stats)
            except Exception as e:
                print(f"[TRINITY][AUTOPSY][ERROR] {e}", flush=True)

def tail_thread(name, path):
    print(f'[TRINITY] Watching {name}: {path}')
    try:
        proc = subprocess.Popen(['tail', '-n', '0', '-F', path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        while True:
            line = proc.stdout.readline().decode('utf-8')
            if not line: break
            
            # Detect Errors
            if any(x in line for x in ['ERROR', 'CRITICAL', 'Exception', 'Traceback']):
                threading.Thread(target=trinity_pipeline, args=(name, line.strip())).start()
            
            # Detect Losses for Autopsy
            if 'EXIT' in line and 'pnl=Rp-' in line:
                threading.Thread(target=perform_trade_autopsy, args=(name, line.strip())).start()
    except Exception as e:
        print(f"[TRINITY][TAIL][ERROR] {name}: {e}", flush=True)

if __name__ == '__main__':
    time.sleep(10)
    telegram_send('🛡️ *TRINITY GOVERNOR v3.0 ACTIVE*\n(Secure Execution, Health Monitor, & Autopsy Enabled)')
    threading.Thread(target=health_check_loop, daemon=True).start()
    threading.Thread(target=midnight_evolution, daemon=True).start()
    threading.Thread(target=autonomous_tuning_loop, daemon=True).start()
    threading.Thread(target=autonomous_git_watcher, daemon=True).start()
    for name, path in LOGS_TO_WATCH.items():
        if os.path.exists(path):
            threading.Thread(target=tail_thread, args=(name, path), daemon=True).start()
    while True: time.sleep(1)
