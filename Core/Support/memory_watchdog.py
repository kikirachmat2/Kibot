#!/usr/bin/env python3
import psutil
import os
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] 🐕 WATCHDOG - %(levelname)s - %(message)s')
logger = logging.getLogger("MemoryWatchdog")

THRESHOLD_PERCENT = 85.0

def check_memory():
    mem = psutil.virtual_memory()
    logger.info(f"Memory Usage: {mem.percent}%")
    
    if mem.percent > THRESHOLD_PERCENT:
        logger.warning(f"🚨 High memory usage detected ({mem.percent}%)! Investigating culprits...")
        
        # Find top memory consumers
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
            processes.append(proc.info)
        
        processes.sort(key=lambda x: x['memory_percent'], reverse=True)
        
        for p in processes[:3]:
            logger.info(f"Top Culprit: {p['name']} (PID: {p['pid']}) - {p['memory_percent']:.2f}%")
            
            if 'ollama' in p['name'].lower() or 'python3' in p['name'].lower():
                logger.warning(f"Attempting to restart {p['name']} to free memory...")
                # We don't kill directly, we use systemctl if possible, or just log for now
                # In a real sovereign system, we might restart the service
                if 'ollama' in p['name'].lower():
                    subprocess.run(["sudo", "systemctl", "restart", "ollama"], check=False)

if __name__ == "__main__":
    check_memory()
