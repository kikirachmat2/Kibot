import time, subprocess, json, os, requests, threading, re, shutil, sys
from pathlib import Path
from datetime import datetime

# --- CONFIGURATION ---
REPO_PATH = '/home/ubuntu/KiBot'
# Add Learning System to path
sys.path.append(os.path.join(REPO_PATH, 'Batam/Learning System'))
try:
    from kibot_learning_engine import get_engine
except ImportError:
    get_engine = None

OLLAMA_URL = 'http://127.0.0.1:11435/api/chat'
# ... (rest of config)
OLLAMA_URL = 'http://127.0.0.1:11435/api/chat'
TELEGRAM_BOT_TOKEN = 'REDACTED_TELEGRAM_TOKEN'
TELEGRAM_CHAT_ID = '1346696386'
HEAL_HISTORY_FILE = Path(REPO_PATH) / 'state/trinity_heal_history.jsonl'

LOGS_TO_WATCH = {
    'MANAGER': REPO_PATH + '/logs/manager.log',
    'EXECUTOR': REPO_PATH + '/logs/executor.log',
    'SCANNER': REPO_PATH + '/logs/scanner.log'
}

def send_telegram(message):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def ask_ollama(prompt):
    try:
        payload = {'model': 'qwen3:0.6b', 'messages': [{'role': 'user', 'content': prompt}], 'stream': False}
        r = requests.post(OLLAMA_URL, json=payload, timeout=30)
        return r.json()['message']['content'].strip()
    except: return None

def ask_copilot(problem_desc, retry_info=''):
    try:
        prompt = f'suggest a one-line bash command to fix this: {problem_desc}. {retry_info}'
        # Using -p for direct output
        cmd = f'copilot -p "{prompt}"'
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode()
        for line in output.split('\n'):
            if any(x in line for x in ['sudo', 'systemctl', 'rm ', 'mkdir', 'cp ', 'sed ']):
                return line.strip()
    except: return None

def deploy_and_verify(name, fix_cmd):
    try:
        subprocess.run(fix_cmd, shell=True, check=True)
        time.sleep(5)
        verify_cmd = f'systemctl is-active kibot-{name.lower()}'
        res = subprocess.run(verify_cmd, shell=True, capture_output=True, text=True)
        return 'active' in res.stdout
    except: return False

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
                send_telegram(f'✅ *TRINITY HEALED (Attempt {retries+1})*\n🔍 {name}\n🛠️ `{fix_cmd}`\n🚀 Status: NORMAL')
                return
            else:
                retries += 1
                retry_msg = f'Last fix ({fix_cmd}) failed. Try a different approach.'
        else:
            retries += 1
            
    send_telegram(f'❌ *TRINITY FAILED*\n🔍 {name}\n⚠️ Error: {error_line}\nStatus: *Gagal setelah 3 kali percobaan.*')

def health_check_loop():
    engine = get_engine() if get_engine else None
    while True:
        try:
            # 1. Learning Patrol (New Agentic Memory)
            if engine:
                engine.patrol_and_audit()
                
            # 2. RAM Check using python psutil-like logic (cleaner)
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()
                total = int(lines[0].split()[1])
                free = int(lines[1].split()[1])
                used_pct = ((total - free) / total) * 100
                
            if used_pct > 90.0:
                send_telegram(f'⚠️ *SYSTEM ALERT*: RAM Usage {used_pct:.1f}%. Optimizing...')
                subprocess.run('sudo sync && echo 3 | sudo tee /proc/sys/vm/drop_caches', shell=True)
            
            # Disk Check
            usage = shutil.disk_usage('/')
            percent = (usage.used / usage.total) * 100
            if percent > 90.0:
                send_telegram(f'⚠️ *SYSTEM ALERT*: Disk Usage {percent:.1f}%. Cleaning logs...')
                subprocess.run(f'find {REPO_PATH}/logs/ -name "*.log" -mtime +7 -delete', shell=True)
                
        except: pass
        time.sleep(300)

def midnight_evolution():
    while True:
        now = datetime.now()
        if now.hour == 0 and now.minute == 0:
            send_telegram('🌙 *MIDNIGHT EVOLUTION INITIATED*')
            idea = ask_copilot('research online for new HFT trading features or server optimizations for a Python bot on OCI Ampere. suggest one actionable improvement.')
            if idea:
                send_telegram(f'💡 *EVOLUTION IDEA*:\n{idea}')
            time.sleep(60)
        time.sleep(30)

def perform_trade_autopsy(name, line):
    engine = get_engine() if get_engine else None
    if not engine: return
    
    # Extract pair and loss from log line
    # Format: [TRADELOG] EXIT btc_idr pnl=Rp-1000 (-2.00%) hold=10m reason=stop_loss
    match = re.search(r'EXIT\s+(\w+)\s+pnl=Rp(-\d+)\s+\(([-\d.]+)%\)', line)
    if match:
        pair = match.group(1)
        pnl_pct = match.group(3)
        reason = "Unknown"
        if "reason=" in line: reason = line.split("reason=")[1].split()[0]
        
        prompt = f"Analyze this trading loss for {pair}. PnL: {pnl_pct}%. Reason: {reason}. Context: {line}. Why did it lose and what is the lesson? Answer in 1 short sentence."
        lesson = ask_ollama(prompt)
        if lesson:
            send_telegram(f"🔬 *AI AUTOPSY ({pair})*:\n{lesson}")
            # Save lesson to Redis/Learning Engine
            stats = engine.get_stats(pair)
            stats.lessons.append(f"{datetime.now().strftime('%Y-%m-%d')}: {lesson}")
            engine.save_stats(stats)

def tail_thread(name, path):
    print(f'[TRINITY] Watching {name}: {path}')
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

if __name__ == '__main__':
    # Give it some time to ensure network is up
    time.sleep(10)
    send_telegram('🛡️ *TRINITY GOVERNOR v2.0 ACTIVE*\n(Retry Logic, Health Monitor, & Midnight Evolution Enabled)')
    threading.Thread(target=health_check_loop, daemon=True).start()
    threading.Thread(target=midnight_evolution, daemon=True).start()
    for name, path in LOGS_TO_WATCH.items():
        if os.path.exists(path):
            threading.Thread(target=tail_thread, args=(name, path), daemon=True).start()
    while True: time.sleep(1)
