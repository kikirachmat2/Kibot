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
import httpx

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
from Core_Logic.council_data_aggregator import CouncilDataAggregator

# Global Config
try:
    from Support.ki_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
except ImportError:
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
        self.aggregator = CouncilDataAggregator(self)
        self.last_state = {}
        self.market_mood = "NEUTRAL"
        self.is_running = True
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
        """High-integrity Monitoring: Combines Watchman, CircuitBreaker, and Oracle Scouting."""
        logger.info("🛰️ High-Integrity Mesh Monitor started.")
        
        # Immediate Oracle Scout on startup
        logger.info("Oracle Mode (Startup): Performing initial market scouting...")
        await self.deliberate_issue("SCOUTING", {"type": "PROACTIVE_ORACLE", "snapshot": await self.get_telemetry()})
        
        iteration = 0
        last_dashboard_time = 0
        dashboard_interval = 60
        while self.is_running:
            iteration += 1
            
            # 3. Telemetry Update & Snapshot
            try:
                telemetry = await self.get_telemetry()
                snapshot_path = ROOT_DIR / "State" / "telemetry_snapshot.json"
                with open(snapshot_path, "w") as f:
                    json.dump(telemetry, f, indent=2)
                logger.debug("Telemetry snapshot updated.")
            except Exception as e:
                logger.error(f"Telemetry snapshot failed: {e}")

            # 4. Dashboard (Telegram)
            if self.is_running and (time.time() - last_dashboard_time > dashboard_interval):
                await self.send_dashboard(telemetry)
                last_dashboard_time = time.time()
            
            # 1. CIRCUIT BREAKER CHECK (Physical Node Health)
            for name, cfg in NODES.items():
                if name == "BATAM": continue
                
                ip = cfg['ip']
                # Determine breaker name (SCANNER or EXECUTOR)
                breaker_key = name.split("_")[-1]
                breaker = self.breakers.get(breaker_key)
                
                if not breaker or not breaker.can_attempt():
                    continue

                try:
                    # Async connection check (Low level port 22)
                    _, writer = await asyncio.wait_for(asyncio.open_connection(ip, 22), timeout=3.0)
                    writer.close()
                    await writer.wait_closed()
                    breaker.record_success()
                except Exception:
                    status = breaker.record_failure()
                    logger.error(f"❌ {name} unreachable (Port 22)!")
                    if status == "ESCALATE":
                        asyncio.create_task(self.deliberate_issue(name, {"type": "NODE_UNREACHABLE", "snapshot": telemetry}))

            # 2. WATCHMAN CHECK (Service Health)
            critical_services = [
                telemetry["redis"] == "OFFLINE",
                telemetry["tailscale"] != "Running",
                telemetry["mesh_nodes"]["SINGAPORE_EXECUTOR"] == "OFFLINE"
            ]
            
            if any(critical_services):
                logger.warning("Watchman: CRITICAL infrastructure anomaly detected!")
                await self.deliberate_issue("EMERGENCY", {"type": "SYSTEM_ANOMALY", "snapshot": telemetry})
            elif telemetry["mesh_nodes"]["SINGAPORE_SCANNER"] == "OFFLINE":
                logger.info("Watchman: Scanner is offline but system remains operational.")
            elif iteration % 60 == 0:
                logger.info("Oracle Mode (Periodic): Council performing proactive market scouting...")
                await self.deliberate_issue("SCOUTING", {"type": "PROACTIVE_ORACLE", "snapshot": telemetry})
            
            # 3. REPORTING
            await self.send_dashboard(telemetry)
            await asyncio.sleep(60)

    async def deliberate_issue(self, target: str, context: Dict):
        """Trigger Council deliberation and execute the resulting strategy."""
        decision = await self.council.deliberate(context)
        
        # Only execute if confidence is high and action is valid
        if decision.get("action") and decision.get("confidence", 0) >= 0.8:
            logger.info(f"Council approved action: {decision['action']}. Executing...")
            await self.execute_action(decision["action"], target)
        else:
            logger.info(f"Council decision: {decision.get('action', 'NONE')} (Confidence: {decision.get('confidence', 0)*100:.1f}%). No action taken.")

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
            async with httpx.AsyncClient() as client:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                await client.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"})

    async def execute_action(self, action: str, target: str = "SYSTEM"):
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
        import shutil
        
        # 1. Base Infrastructure Stats
        telemetry = {
            "timestamp": time.time(),
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "os_load": os.getloadavg() if hasattr(os, "getloadavg") else "N/A",
            "redis": "OFFLINE",
            "tailscale": "OFFLINE",
            "mesh_nodes": {
                "SINGAPORE_SCANNER": "UNKNOWN",
                "SINGAPORE_EXECUTOR": "UNKNOWN"
            },
            "heartbeat": "ACTIVE"
        }
        
        # 2. Add Council & Portfolio Context
        try:
            context = self.aggregator.get_debate_context()
            telemetry["portfolio"] = context.get("portfolio_state", {})
            telemetry["market"] = context.get("market_context", {})
            telemetry["stats"] = context.get("audit_data", {}).get("rejection_analysis", {})
            telemetry["council"] = context.get("philosophy", {})
        except Exception as e:
            logger.error(f"Failed to aggregate council data: {e}")
        
        # Check Local Redis
        redis_path = shutil.which("redis-cli")
        if redis_path:
            try:
                proc = await asyncio.create_subprocess_shell(f"{redis_path} ping", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, _ = await proc.communicate()
                if b"PONG" in stdout: telemetry["redis"] = "ONLINE"
            except: pass
        else:
            logger.debug("redis-cli not found in PATH")

        # Check Tailscale & Remote Nodes (Singapore)
        ts_path = shutil.which("tailscale")
        if ts_path:
            try:
                # Check local TS status
                proc = await asyncio.create_subprocess_shell(f"{ts_path} status --json", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, _ = await proc.communicate()
                if stdout:
                    ts_data = json.loads(stdout)
                    telemetry["tailscale"] = ts_data.get("BackendState", "ONLINE")
                    
                    # Proactive Mesh Check (Tailscale IPs for Singapore nodes)
                    nodes = {"SINGAPORE_SCANNER": "sg-scanner", "SINGAPORE_EXECUTOR": "sg-executor"}
                    for name, host in nodes.items():
                        ping = await asyncio.create_subprocess_shell(f"ping -c 1 -W 1 {host}", stdout=asyncio.subprocess.PIPE)
                        await ping.wait()
                        telemetry["mesh_nodes"][name] = "ONLINE" if ping.returncode == 0 else "OFFLINE"
            except: pass
        else:
            logger.debug("tailscale not found in PATH")

        return telemetry


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
