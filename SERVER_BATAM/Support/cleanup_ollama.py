#!/usr/bin/env python3
import subprocess
import json
import os

# Models to KEEP
WHITELIST = {
    "qwen3.5:4b",
    "qwen3.5:9b",
    "nomic-embed-text:latest",
}

def get_models():
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, check=True)
        lines = result.stdout.strip().split("\n")
        if len(lines) <= 1:
            return []
        
        models = []
        for line in lines[1:]: # Skip header
            parts = line.split()
            if parts:
                models.append(parts[0])
        return models
    except Exception as e:
        print(f"[CLEANUP] Failed to list models: {e}")
        return []

def remove_model(model_name):
    print(f"[CLEANUP] Removing redundant model: {model_name}")
    try:
        subprocess.run(["ollama", "rm", model_name], check=True)
        return True
    except Exception as e:
        print(f"[CLEANUP] Failed to remove {model_name}: {e}")
        return False

def main():
    models = get_models()
    removed_count = 0
    
    for model in models:
        if model not in WHITELIST:
            if remove_model(model):
                removed_count += 1
                
    if removed_count > 0:
        print(f"[CLEANUP] Finished. Removed {removed_count} models.")
    else:
        print("[CLEANUP] All models are in whitelist. No action taken.")

if __name__ == "__main__":
    main()
