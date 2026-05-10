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
from typing import Dict, List, Optional
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load Environment Variables
load_dotenv()

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
from Core.circuit_breaker import CircuitBreaker
from Core.sovereign_council import SovereignCouncil

# Global Config (Formerly in Manager)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

NODES = {
    "BATAM": {"ip": "127.0.0.1", "role": "MASTER"},
    "SINGAPORE_SCANNER": {"ip": "100.105.139.21", "role": "SCANNER", "services": ["kibot-mesh"]},
    "SINGAPORE_EXECUTOR": {"ip": "100.103.77.10", "role": "EXECUTOR", "services": ["kibot-mesh"]}
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
        self.last_state = {"portfolio": {"equity_idr": 0, "daily_pnl": "0.0%", "active_positions": []}}
        self.market_mood = "NEUTRAL"
        self.brain = None
        
        # Self-Healing: Reset AI Provider Cooldowns on start
        provider_cache = ROOT_DIR / "Data" / "AI" / "ai_coordinator_providers.json"
        if provider_cache.exists():
            try:
                provider_cache.unlink()
                logger.info("🔥 AI Provider Cooldowns Reset Successfully.")
            except Exception as e:
                logger.error(f"❌ Failed to reset AI cooldowns: {e}")
        
        self.brain = {"status": "IDLE", "memory": []}
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
            f"Reasoning: {decision['reasoning']}"
        )
        await self.send_telegram(msg)
        
        if decision.get('auto_execute'):
            await self.execute_action(decision['action'], target)

    async def send_dashboard(self, telemetry: Dict):
        """Generates and sends the Sovereign Dashboard to Telegram."""
        exec_status = telemetry["mesh_nodes"].get("SINGAPORE_EXECUTOR", "OFFLINE")
        scan_status = telemetry["mesh_nodes"].get("SINGAPORE_SCANNER", "OFFLINE")
        
        # Calculate Sovereign Status
        if exec_status == "ONLINE":
            live_status = "🟢 ACTIVE (FULL TRINITY)" if scan_status == "ONLINE" else "🟢 ACTIVE (DUAL-NODE MODE)"
            ai_status = "🟢 ONLINE"
        else:
            live_status = "🔴 OFFLINE (MESH BROKEN)"
            ai_status = "🔴 OFFLINE"

        msg = (
            f"KIBOT SOVEREIGN DASHBOARD\n"
            f"🕒 {datetime.now().strftime('%H:%M:%S WIB')}\n"
            f"───────────────────\n\n"
            f"📈 Live Trading: {live_status}\n\n"
            f"🏝️ Batam Master:\n"
            f"cpu: {telemetry.get('os_load', ['0'])[0]}%\nram: N/A\ndisk: N/A\n\n"
            f"⚡ Executor Engine ({'🟢 ONLINE' if exec_status == 'ONLINE' else '🔴 OFFLINE'}):\n"
            f"📡 Scanner Senses ({'🟢 ONLINE' if scan_status == 'ONLINE' else '🔴 UNREACHABLE'}):\n\n"
            f"🤖 AI Status: {ai_status}\n"
            f"───────────────────\n"
            f"🛡️ Data sourced directly from Batam Master"
        )
        await self.send_telegram(msg)

    async def send_telegram(self, message: str):
        """Helper to send alerts to Telegram."""
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            import httpx
            async with httpx.AsyncClient() as client:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                await client.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"})

    async def execute_action(self, action: str, target: str):
        """Execute autonomous actions approved by Council."""
        logger.info(f"Executing Council Action: {action} on {target}")
        
        # Mapping Council actions to System commands
        actions_map = {
            "RESTART_MESH": "sudo systemctl restart kibot-mesh",
            "RESTART_SERVICE": f"sudo systemctl restart {target.lower()}",
            "RECONNECT_ADB": "/Users/kiki/Documents/Web\\ Develop/KiBot/Batam/Infrastructure/Automation/adb_bridge.sh",
            "CLEAN_CACHE": "rm -rf /Users/kiki/Documents/Web\\ Develop/KiBot/Batam/state/*.tmp",
            "SELF_HEAL_CODE": f"aider --message 'Fix the bug reported in {target}'"
        }
        
        cmd = actions_map.get(action.upper())
        if cmd:
            try:
                # Use subprocess to run system commands
                process = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                if process.returncode == 0:
                    logger.info(f"✅ Action {action} SUCCESSFUL")
                    await self.send_telegram(f"✅ **Auto-Fix Success**: `{action}` executed on `{target}`")
                else:
                    logger.error(f"❌ Action {action} FAILED: {stderr.decode()}")
                    await self.send_telegram(f"❌ **Auto-Fix Failed**: `{action}` on `{target}`\nError: `{stderr.decode()[:100]}`")
            except Exception as e:
                logger.error(f"Execution error: {e}")
        else:
            logger.warning(f"Action {action} not recognized by Master.")

    async def get_telemetry(self) -> Dict:
        """Gather real-time telemetry from Batam and remote Singapore nodes."""
        telemetry = {
            "timestamp": time.time(),
            "os_load": os.getloadavg() if hasattr(os, "getloadavg") else "N/A",
            "redis": "OFFLINE",
            "tailscale": "OFFLINE",
            "mesh_nodes": {
                "SINGAPORE_SCANNER": "UNKNOWN",
                "SINGAPORE_EXECUTOR": "UNKNOWN"
            },
            "heartbeat": "ACTIVE"
        }
        
        # Check Local Redis
        try:
            proc = await asyncio.create_subprocess_shell("redis-cli ping", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, _ = await proc.communicate()
            if b"PONG" in stdout: telemetry["redis"] = "ONLINE"
        except: pass

        # Check Tailscale & Remote Nodes (Singapore)
        try:
            # Check local TS status
            proc = await asyncio.create_subprocess_shell("tailscale status --json", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, _ = await proc.communicate()
            if stdout:
                ts_data = json.loads(stdout)
                telemetry["tailscale"] = ts_data.get("BackendState", "ONLINE")
                
                # Proactive Mesh Check (Tailscale IPs for Singapore nodes)
                nodes = {"SINGAPORE_SCANNER": "sg-scanner", "SINGAPORE_EXECUTOR": "sg-executor"}
                for name, host in nodes.items():
                    ping = await asyncio.create_subprocess_shell(f"ping -c 1 -W 2 {host}", stdout=asyncio.subprocess.PIPE)
                    await ping.wait()
                    telemetry["mesh_nodes"][name] = "ONLINE" if ping.returncode == 0 else "OFFLINE"
        except: pass

        return telemetry

    async def mesh_monitor_loop(self):
        """Main loop with Mesh Awareness and Oracle Mode (Proactive Scouting)."""
        logger.info("🛰️ Mesh Monitor Loop started.")
        
        # Immediate Oracle Scout on startup for validation
        logger.info("Oracle Mode (Startup): Performing initial market scouting...")
        await self.deliberate_issue("SCOUTING", {"type": "PROACTIVE_ORACLE", "snapshot": await self.get_telemetry()})
        
        iteration = 0
        while self.is_running:
            iteration += 1
            telemetry = await self.get_telemetry()
            
            # 1. REACTIVE: Watchman Logic (Batam/Mesh failures)
            # Check if critical services are down (Scanner is now considered OPTIONAL)
            critical_services = [
                telemetry["redis"] == "OFFLINE",
                telemetry["tailscale"] != "Running",
                # telemetry["mesh_nodes"]["SINGAPORE_SCANNER"] == "OFFLINE", # [v9.5] Scanner is optional
                telemetry["mesh_nodes"]["SINGAPORE_EXECUTOR"] == "OFFLINE"
            ]
            
            if any(critical_services):
                logger.warning("Watchman detected a CRITICAL infrastructure anomaly! Triggering Council...")
                await self.deliberate_issue("EMERGENCY", {"type": "SYSTEM_ANOMALY", "snapshot": telemetry})
            elif telemetry["mesh_nodes"]["SINGAPORE_SCANNER"] == "OFFLINE":
                logger.info("Watchman: Scanner is offline but system remains operational.")
            elif iteration % 60 == 0:
                logger.info("Oracle Mode (Periodic): Council performing proactive market scouting...")
                await self.deliberate_issue("SCOUTING", {"type": "PROACTIVE_ORACLE", "snapshot": telemetry})
            
            # 2. REPORTING: Push status to Telegram (Now safe here)
            await self.send_dashboard(telemetry)
            
            await asyncio.sleep(60)

    async def deliberate_issue(self, target: str, context: Dict):
        """Trigger Council deliberation and execute the resulting strategy."""
        decision = await self.council.deliberate(context)
        
        # Only execute if confidence is high and action is valid
        if decision.get("action") and decision.get("confidence", 0) >= 0.8:
            logger.info(f"Council approved action: {decision['action']}. Executing...")
            await self.execute_action(decision["action"])
        else:
            logger.info(f"Council decision: {decision.get('action', 'NONE')} (Confidence: {decision.get('confidence', 0)*100:.1f}%). No action taken.")

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
