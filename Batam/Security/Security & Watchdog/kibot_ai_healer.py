#!/usr/bin/env python3
import time, subprocess, json, os, requests, threading

# Config
OLLAMA_URL = "http://127.0.0.1:11435/api/chat"
TOKEN = os.getenv("KIBOT_OLLAMA_GATEWAY_TOKEN")
REPO_PATH = "/home/ubuntu/KiBot"

# Remote Nodes to Watch
NODES = {
    "LOCAL": {"host": "localhost", "log": "/home/ubuntu/KiBot/logs/manager.log"},
    "EXECUTOR": {"host": "100.122.1.109", "log": "/home/ubuntu/KiBot/logs/executor.log", "key": "/home/ubuntu/.ssh/id_github_kibot"},
    "SCANNER": {"host": "100.105.139.21", "log": "/home/ubuntu/KiBot/logs/scanner.log", "key": "/home/ubuntu/.ssh/id_github_kibot"}
}

def report_to_github(node_name, action_taken):
    """Fungsi buat catat aksi penyembuhan ke GitHub secara otomatis"""
    try:
        os.chdir(REPO_PATH)
        subprocess.run(["git", "add", "."], check=False)
        commit_msg = f"[AI-HEALER][{node_name}] Auto-Fix Applied: {action_taken}"
        subprocess.run(["git", "commit", "-m", commit_msg], check=False)
        subprocess.run(["git", "push", "origin", "main"], check=False)
        print(f"[GITHUB] Action reported to repository.")
    except Exception as e:
        print(f"[GITHUB][ERROR] Failed to push report: {e}")

def ask_ai_healer(node_name, error_msg):
    # Coba pake Ollama dulu (Cepet & Lokal)
    prompt = f"System Error on {node_name}: {error_msg}\n\nProvide a one-line bash command to fix this. Respond ONLY with the command."
    headers = {"Authorization": f"Bearer {TOKEN}"}
    payload = {
        "model": "qwen3:0.6b", "messages": [{"role": "user", "content": prompt}], "stream": False
    }
    try:
        r = requests.post(OLLAMA_URL, json=payload, headers=headers, timeout=15)
        res = r.json()['message']['content'].strip()
        if "systemctl" in res or "rm" in res or "mkdir" in res: return res
    except: pass

    # FALLBACK: Pake GitHub Copilot CLI (Lebih Pinter)
    print(f"[AI-HEALER] Asking GitHub Copilot for solution...")
    try:
        # Pake flag -- biar gh gak bingung
        cmd = f"gh copilot suggest -t shell \"{error_msg}\" --"
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode()
        # Ambil baris yang keliatan kayak perintah shell
        for line in output.split('\n'):
            if any(x in line for x in ["systemctl", "rm ", "mkdir ", "cp ", "sed "]):
                return line.strip()
    except: return None

def watch_node(name, config):
    print(f"[AI-HEALER] Watching {name} at {config['host']}")
    if name == "LOCAL":
        cmd = ["tail", "-F", config['log']]
    else:
        cmd = ["ssh", "-i", config['key'], "-o", "StrictHostKeyChecking=no", f"ubuntu@{config['host']}", f"tail -F {config['log']}"]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while True:
        line = proc.stdout.readline().decode('utf-8')
        if not line: break
        if any(x in line for x in ["ERROR", "Traceback", "Exception", "CRITICAL"]):
            print(f"[AI-HEALER][{name}] Detected: {line.strip()}")
            fix_cmd = ask_ai_healer(name, line)
            if fix_cmd:
                print(f"[AI-HEALER][{name}] AI Suggested Fix: {fix_cmd}")
                if name == "LOCAL":
                    subprocess.run(fix_cmd, shell=True, check=False)
                else:
                    subprocess.run(["ssh", "-i", config['key'], f"ubuntu@{config['host']}", fix_cmd], check=False)
                report_to_github(name, fix_cmd)

def monitor():
    threads = []
    for name, config in NODES.items():
        t = threading.Thread(target=watch_node, args=(name, config))
        t.start()
        threads.append(t)
    for t in threads: t.join()

if __name__ == "__main__":
    monitor()
