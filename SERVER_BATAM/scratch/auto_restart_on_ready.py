#!/usr/bin/env python3
import subprocess
import time
import os

MODEL_NAME = "qwen2.5-coder:7b"

def is_model_ready():
    res = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    return MODEL_NAME in res.stdout

def restart_kibot():
    print(f"🚀 Model {MODEL_NAME} is READY! Restarting KiBot...")
    subprocess.run(["pkill", "-f", "KiBot.py"])
    time.sleep(2)
    # Start fresh
    cmd = "export PYTHONPATH=$PYTHONPATH:$(pwd) && nohup python3 SERVER_BATAM/KiBot.py > kibot_master.out 2>&1 &"
    subprocess.Popen(cmd, shell=True)
    print("✅ KiBot Master Restarted with Full AI Power.")

if __name__ == "__main__":
    print(f"🕵️ Waiting for {MODEL_NAME} to finish downloading...")
    while not is_model_ready():
        time.sleep(60) # Check every minute
    
    restart_kibot()
