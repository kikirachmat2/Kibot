#!/usr/bin/env python3
"""
KiBot Sovereign Master Node (Batam)
===================================
The centralized intelligence and control hub for the KiBot Trinity Mesh.
Integrates Sovereign Council deliberation and autonomous system healing.
"""

import os
import sys
import json
import time
import asyncio
import logging
import threading
import subprocess
import platform
import socket
from pathlib import Path
from datetime import datetime

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("kibot_sovereign.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("KiBotMaster")

# Path Setup
ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))

# Core Imports
from SERVER_BATAM.Core.circuit_breaker import CircuitBreaker
from SERVER_BATAM.Core.sovereign_council import SovereignCouncil

# Global Config (Formerly in Manager)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

NODES = {
    "BATAM": {"ip": "127.0.0.1", "role": "MASTER"},
    "SINGAPORE_SCANNER": {"ip": "152.69.218.198", "role": "SCANNER", "services": ["kibot-mesh"]},
    "SINGAPORE_EXECUTOR": {"ip": "168.110.201.228", "role": "EXECUTOR", "services": ["kibot-mesh"]}
}

class KiBotMaster:
    def __init__(self):
        self.council = SovereignCouncil()
        self.breakers = {
            "SCANNER": CircuitBreaker("SCANNER", max_failures=3, reset_after_sec=600),
            "EXECUTOR": CircuitBreaker("EXECUTOR", max_failures=3, reset_after_sec=600),
            "OLLAMA": CircuitBreaker("OLLAMA", max_failures=5, reset_after_sec=120)
        }
        self.is_running = True
        logger.info("Initializing KiBot Sovereign Master...")

    # --- Mesh Monitoring ---
    async def mesh_monitor_loop(self):
        """Continuously monitors node health and triggers Council on failure."""
        logger.info("Starting Mesh Health Monitor...")
        while self.is_running:
            for name, cfg in NODES.items():
                if name == "BATAM": continue
                
                ip = cfg['ip']
                breaker = self.breakers.get(name.split("_")[-1])
                
                if not breaker or not breaker.can_attempt():
                    continue

                try:
                    # Async connection check
                    _, writer = await asyncio.wait_for(asyncio.open_connection(ip, 22), timeout=3.0)
                    writer.close()
                    await writer.wait_closed()
                    breaker.record_success()
                    # logger.info(f"✅ {name} is alive.")
                except Exception:
                    status = breaker.record_failure()
                    logger.error(f"❌ {name} unreachable!")
                    
                    if status == "ESCALATE":
                        # TRIGGER COUNCIL DELIBERATION
                        asyncio.create_task(self.invoke_council(name, "NODE_UNREACHABLE"))
            
            await asyncio.sleep(30) # Observer frequency as per spec

    async def invoke_council(self, target: str, issue_type: str):
        """Invoke the Sovereign Council for complex decision making."""
        context = {
            "type": issue_type,
            "target": target,
            "snapshot": {
                "node": target,
                "timestamp": time.time(),
                "failures": self.breakers.get(target.split("_")[-1], {}).get_status() if self.breakers.get(target.split("_")[-1]) else {}
            }
        }
        
        decision = await self.council.deliberate(context)
        
        # Execute Decision
        msg = (
            f"🧠 **Council Decision: {target}**\n"
            f"Action: `{decision['action']}`\n"
            f"Confidence: `{decision['confidence']*100:.1f}%`\n"
            f"Risk: `{decision['risk']}`\n"
            f"Auto: {'✅' if decision['auto_execute'] else '❌'}\n\n"
            f"Reasoning: {decision['reasoning']}"
        )
        await self.send_telegram(msg)
        
        if decision['auto_execute']:
            await self.execute_action(decision['action'], target)

    async def execute_action(self, action: str, target: str):
        """Execute autonomous actions approved by Council."""
        logger.info(f"Executing Council Action: {action} on {target}")
        # Implementation of SSH restart logic etc.
        # This is where the Executor Bridge lives.
        pass

    async def send_telegram(self, text: str):
        """Helper to send telegram notifications without blocking."""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
        import httpx
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
                )
        except Exception as e:
            logger.error(f"Telegram failed: {e}")

    def start(self):
        # Start core loops
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Add tasks
        loop.create_task(self.mesh_monitor_loop())
        
        logger.info("🎖️ KiBot Sovereign Master is fully OPERATIONAL.")
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            self.is_running = False
            logger.info("Shutting down Sovereign Node...")

if __name__ == "__main__":
    master = KiBotMaster()
    master.start()
