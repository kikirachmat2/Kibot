#!/usr/bin/env python3
from __future__ import annotations
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
from Core.Support.ki_vault import load_sovereign_env
import httpx
import signal

# Load Sovereign Environment (Decrypted)
load_sovereign_env()

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

# Core Imports (Unified Structure)
from Core.circuit_breaker import CircuitBreaker
from Core.sovereign_council import SovereignCouncil
from Core.sovereign_notifier import SovereignNotifier
from Core.Intelligence.aggregator import CouncilDataAggregator

import re
import shlex

SAFE_COMMAND_PATTERNS = [
    r'^systemctl (status|is-active|restart|start|stop) kibot-\w+(\.service)?$',
    r'^systemctl (status|is-active|restart|start|stop) lazarus-ampere(\.service)?$',
    r'^find /home/ubuntu/KiBot/logs/ -name ".*\.log" -mtime \+\d+ -delete$',
    r'^sudo sync && echo 3 \| sudo tee /proc/sys/vm/drop_caches$',
    r'^df -h .*$',
    r'^free -h$',
    r'^uptime$'
]

NODES = {
    "BATAM": {"ip": "127.0.0.1", "role": "MASTER"},
    "SINGAPORE_SCANNER": {"ip": "100.105.139.21", "role": "SCANNER", "services": ["kibot-scanner"]},
    "SINGAPORE_EXECUTOR": {"ip": "100.122.1.109", "role": "EXECUTOR", "services": ["kibot-executor-engine", "kibot-polymarket"]}
}

class KiBotMaster:
    def __init__(self):
        from Core.ki_brain import BrainManager
        self.brain = BrainManager()
        self.council = SovereignCouncil()
        self.council.brain = self.brain # Inject brain
        self.aggregator = CouncilDataAggregator(self)
        self.is_running = True
        self.last_state = {"portfolio": {"equity_idr": 0, "daily_pnl": "0.0%", "active_positions": []}}
        self.market_mood = "NEUTRAL"
        self.breakers = {
            "SCANNER": CircuitBreaker("SCANNER", max_failures=3, reset_after_sec=600),
            "EXECUTOR": CircuitBreaker("EXECUTOR", max_failures=3, reset_after_sec=600),
            "OLLAMA": CircuitBreaker("OLLAMA", max_failures=5, reset_after_sec=120)
        }
        self._emergency_cooldown = {}
        self.notifier = SovereignNotifier()
        
        # Self-Healing: Reset AI Provider Cooldowns on start
        provider_cache = ROOT_DIR / "Core" / "state" / "ai_coordinator_providers.json"
        if provider_cache.exists():
            try:
                provider_cache.unlink()
                logger.info("🔥 AI Provider Cooldowns Reset Successfully.")
            except Exception as e:
                logger.error(f"❌ Failed to reset AI cooldowns: {e}")
        
        logger.info("Initializing KiBot Sovereign Master...")

    def is_command_safe(self, cmd: str) -> bool:
        """Verify if a command is allowed to be executed by the AI."""
        if cmd == 'sudo sync && echo 3 | sudo tee /proc/sys/vm/drop_caches':
            return True
        for pattern in SAFE_COMMAND_PATTERNS:
            if re.match(pattern, cmd):
                return True
        return False

    def tail_logs(self, name, path):
        """Monitor logs for critical errors in the background."""
        logger.info(f'🛡️ Governor: Watching {name} at {path}')
        if not os.path.exists(path):
            logger.warning(f"Log path not found: {path}")
            return
            
        try:
            # Using tail -F to handle log rotation
            proc = subprocess.Popen(['tail', '-n', '0', '-F', path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            while self.is_running:
                line = proc.stdout.readline().decode('utf-8')
                if not line: break
                if any(x in line for x in ['ERROR', 'CRITICAL', 'Exception', 'Traceback']):
                    logger.warning(f"🔍 [LOG ALERT ({name})] {line.strip()}")
                    # Decision to alert human or self-heal can be made here
        except Exception as e:
            logger.error(f"Log Watcher Error ({name}): {e}")

    # --- Signal & Command Plane ---
    async def signal_listener_loop(self):
        """Listens for HMAC-signed high-priority signals from all scanner sources."""
        from Core.Support.ki_utils import verify_signature, sign_payload
        secret = os.environ.get("KIBOT_SECRET", "default_sovereign_secret")
        
        logger.info("📡 Council Signal Listener active on UDP:9991")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", 9991))
        sock.setblocking(False)
        
        loop = asyncio.get_event_loop()
        while self.is_running:
            try:
                data, addr = await loop.sock_recvfrom(sock, 8192)
                envelope = json.loads(data.decode())
                payload = envelope.get("data", {})
                signature = envelope.get("signature", "")
                
                if verify_signature(payload, signature, secret):
                    if payload.get("type") == "COUNCIL_SIGNAL_DATA":
                        signals = payload.get("signals", [])
                        logger.info(f"🏛️ Received {len(signals)} signed signals from {addr}. Deliberating...")
                        
                        async def deliberate_and_dispatch(sigs):
                            now = datetime.now()
                            is_midnight = (now.hour == 23 and now.minute >= 45)
                            decision = await self.council.deliberate_trading({
                                "signals": sigs, 
                                "source": addr[0],
                                "is_midnight_approaching": is_midnight
                            })
                            
                            if not decision or not isinstance(decision, dict):
                                logger.warning("⚠️ Council returned invalid or empty decision.")
                                return

                            if decision.get("status") == "EXECUTING":
                                action = decision.get("action", "UNKNOWN")
                                ticker = decision.get("ticker", "UNKNOWN")
                                logger.info(f"🚀 [MANDATE] Council approved {action} {ticker}.")
                                
                                # Prepare mandate for Executor
                                mandate_data = {
                                    "type": "COUNCIL_MANDATE",
                                    "symbol": decision["ticker"],
                                    "side": decision["action"],
                                    "price": decision.get("source_signal", {}).get("price", 0),
                                    "confidence": decision.get("confidence", 0),
                                    "reason": decision.get("logic", "Council Mandate")[:100]
                                }
                                
                                # Send HMAC-signed mandate to Indodax Executor (Port 9998)
                                envelope_out = {
                                    "data": mandate_data,
                                    "signature": sign_payload(mandate_data, secret)
                                }
                                sock_out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                                sock_out.sendto(json.dumps(envelope_out).encode(), ("127.0.0.1", 9998))
                                
                        asyncio.create_task(deliberate_and_dispatch(signals))
                else:
                    logger.warning(f"🛡️ REJECTED: Invalid HMAC signature from {addr}")
                    
            except Exception as e:
                if self.is_running:
                    logger.error(f"Signal Listener Error: {e}")
                await asyncio.sleep(0.1)

    # --- Mesh Monitoring ---
    async def mesh_monitor_loop(self):
        """High-integrity Monitoring: Combines Watchman, CircuitBreaker, and Oracle Scouting."""
        logger.info("🛰️ High-Integrity Mesh Monitor started.")
        
        # Start Signal Listener in background
        asyncio.create_task(self.signal_listener_loop())
        
        # Immediate Oracle Scout on startup
        logger.info("Oracle Mode (Startup): Performing initial market scouting...")
        await self.deliberate_issue("SCOUTING", {"type": "PROACTIVE_ORACLE", "snapshot": await self.get_telemetry()}, alert=False)
        
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

            # 4. Dashboard (Telegram) - DISABLED (MasterNode no longer spams)
            # if self.is_running and (time.time() - last_dashboard_time > dashboard_interval):
            #     await self.send_dashboard(telemetry)
            #     last_dashboard_time = time.time()
            
            # 1. CIRCUIT BREAKER CHECK (Physical Node Health)
            # Since everything is local, we just check if local services are responsive
            pass

            # 2. WATCHMAN CHECK (Service Health)
            critical_services = [
                telemetry["redis"] == "OFFLINE",
                # Add more local service checks here if needed
            ]
            
            if any(critical_services):
                logger.warning("Watchman: CRITICAL infrastructure anomaly detected!")
                await self.notifier.send_urgent_alert(
                    "CRITICAL infrastructure anomaly detected! Redis is OFFLINE.",
                    "INFRASTRUCTURE_FAILURE"
                )
                await self.deliberate_issue("EMERGENCY", {"type": "SYSTEM_ANOMALY", "snapshot": telemetry}, alert=False)
            # 3. PERSISTENCE & REPORTING
            try:
                now = datetime.now()
                # A. Midnight Report (00:00 WIB)
                if now.hour == 0 and now.minute == 0:
                    if not hasattr(self, '_midnight_sent') or self._midnight_sent != now.day:
                        logger.info("Midnight reached. Sending Sovereign Daily Report...")
                        await self.notifier.send_status_reply(telemetry)
                        self._midnight_sent = now.day
                
                # B. Periodic Council Deliberation (Scouting) - SILENT (No Telegram)
                if iteration % 60 == 0:
                    logger.info("Oracle Mode: Periodic scouting (Silent)...")
                    await self.deliberate_issue("SCOUTING", {"type": "PROACTIVE_ORACLE", "snapshot": telemetry}, alert=False)
                    
            except Exception as e:
                logger.error(f"Failed to process telemetry: {e}")

            # Guaranteed sleep
            await asyncio.sleep(60)

    async def deliberate_issue(self, target: str, context: Dict, alert: bool = True):
        """Trigger Council deliberation and execute the resulting strategy."""
        decision = await self.council.deliberate(context)
        if not decision or not isinstance(decision, dict):
             logger.warning(f"⚠️ Council returned invalid decision for {target}")
             return
        
        # Only execute if confidence is high and action is valid
        if decision.get("action") and decision.get("confidence", 0) >= 0.8:
            if alert:
                msg = (
                    f"🚨 **Urgent Trouble Detected**\n"
                    f"Node: {target}\n"
                    f"Action: `{decision['action']}`\n"
                    f"Reasoning: {decision['reasoning']}"
                )
                await self.notifier.send_urgent_alert(msg, f"COUNCIL_ACTION_{target}")
            
            logger.info(f"Council approved action: {decision['action']}. Executing...")
            await self.execute_action(decision["action"], target, notify=alert)
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
        if not decision or not isinstance(decision, dict):
            logger.warning(f"⚠️ Council failed to return a valid decision for {target}")
            return
        
        # Execute Decision
        msg = (
            f"🧠 **Council Decision: {target}**\n"
            f"Action: `{decision.get('action', 'NONE')}`\n"
            f"Confidence: `{decision.get('confidence', 0)*100:.1f}%`\n"
            f"Risk: `{decision.get('risk', 'UNKNOWN')}`\n"
            f"Reasoning: {decision.get('reasoning', 'No reasoning provided.')}"
        )
        await self.notifier.send_urgent_alert(msg, f"COUNCIL_DECISION_{target}")
        
        if decision.get('auto_execute'):
            await self.execute_action(decision['action'], target)

    async def execute_action(self, action: str, target: str, notify: bool = True):
        """Executes a recovery action (restart service, reboot, etc) with safety check."""
        logger.info(f"Executing recovery action: {action} on {target}")
        
        # Mapping actions to shell commands
        commands = {
            "RESTART_SERVICE": "systemctl restart kibot-high-command",
            "CLEAN_CACHE": "rm -rf /tmp/kibot_cache/*",
            "REBOOT_NODE": "sudo reboot",
            "OLLAMA_PULL": "ollama pull qwen2.5:1.5b",
            "LOG_ROTATE": "logrotate -f /etc/logrotate.d/kibot"
        }
        
        cmd = commands.get(action)
        if cmd:
            if not self.is_command_safe(cmd):
                logger.error(f"🛡️ [SECURITY BLOCK] Attempted unsafe command: {cmd}")
                if notify:
                    await self.notifier.send_urgent_alert(f"🛡️ **Security Block**: Blocked unsafe command `{cmd}` on `{target}`", "SECURITY_BLOCK")
                return

            try:
                proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, stderr = await proc.communicate()
                
                if proc.returncode == 0:
                    logger.info(f"Successfully executed {action}")
                    if notify:
                        await self.notifier.send_urgent_alert(f"✅ **Urgent Fix Applied**: `{action}` on `{target}`", f"FIX_APPLIED_{action}")
                else:
                    logger.error(f"Failed to execute {action}: {stderr.decode()}")
                    if notify:
                        await self.notifier.send_urgent_alert(f"❌ **Urgent Fix Failed**: `{action}` on `{target}`\nError: `{stderr.decode()[:100]}`", f"FIX_FAILED_{action}")
            except Exception as e:
                logger.error(f"Error during action execution: {e}")
        else:
            logger.warning(f"Action {action} not recognized by Master.")

    async def _fetch_json(self, url: str) -> Optional[Dict]:
        """Fetch JSON data from a URL."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.json()
        except Exception:
            pass
        return None

    def _check_local_port(self, port: int) -> bool:
        """Check if a local port is listening."""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex(('127.0.0.1', port)) == 0
        except:
            return False

    async def get_telemetry(self) -> Dict:
        """Gather real-time telemetry from Batam and remote Singapore nodes."""
        import shutil
        import psutil
        
        # 1. Base Infrastructure Stats
        local_stats = {
            "cpu": psutil.cpu_percent(),
            "ram": psutil.virtual_memory().percent,
            "disk": psutil.disk_usage('/').percent
        }
        
        telemetry = {
            "timestamp": time.time(),
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "os_load": os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0),
            "redis": "ONLINE" if self._check_local_port(6379) else "OFFLINE",
            "tailscale": "ONLINE" if self._check_local_port(41641) or os.path.exists("/dev/net/tun") else "OFFLINE",
            "mesh_nodes": {
                "BATAM_MASTER": "ONLINE",
                "SINGAPORE_SCANNER": "UNKNOWN",
                "SINGAPORE_EXECUTOR": "UNKNOWN"
            },
            "system_stats": {
                "BATAM_MASTER": local_stats,
                "SINGAPORE_SCANNER": {"cpu": 0, "ram": 0, "disk": 0},
                "SINGAPORE_EXECUTOR": {"cpu": 0, "ram": 0, "disk": 0}
            },
            "status_text": {
                "activity": "Monitoring Trinity Mesh",
                "difficulty": "No active issues"
            },
            "heartbeat": "ACTIVE"
        }

        # 2. Add Indodax Portfolio Context
        try:
            from Core.Exchange.indodax import IndodaxGateway
            gw = IndodaxGateway()
            info = await gw.get_info()
            if info.get("success") == 1:
                balances = info["return"]["balance"]
                # Filter non-zero balances
                active_pos = [{"coin": k, "amount": v} for k, v in balances.items() if float(v) > 0.000001]
                
                # Get IDR Equity (Total)
                equity_idr = float(balances.get("idr", 0))
                
                # Update last state with more details
                self.last_state["portfolio"] = {
                    "equity_idr": equity_idr,
                    "pnl_idr": 0, # Placeholder until historical tracking is implemented
                    "return_pct": 0.0,
                    "wl_ratio": "0W / 0L",
                    "active_positions": active_pos[:5]
                }
        except Exception as e:
            logger.error(f"Failed to fetch Indodax balance: {e}")

        # 3. Add Polymarket State
        try:
            poly_url = f"http://{NODES['SINGAPORE_EXECUTOR']['ip']}:11600/api/state"
            poly_state = await self._fetch_json(poly_url)
            if poly_state:
                telemetry["polymarket"] = {
                    "status": "ONLINE" if poly_state.get("ready") else "DEGRADED",
                    "equity_idr": 0, # Still placeholder
                    "pnl_idr": 0,
                    "return_pct": 0.0,
                    "wl_ratio": "0W / 0L",
                    "pnl_today": "+0.00%",
                    "pnl_7d": "+0.00%",
                    "pnl_30d": "+0.00%",
                    "active_positions": []
                }
        except: pass

        # 4. Add Council & Market Context
        try:
            context = await self.aggregator.get_debate_context()
            telemetry["portfolio"] = context.get("portfolio_state", {})
            telemetry["market"] = context.get("market_context", {})
            telemetry["stats"] = context.get("audit_data", {}).get("rejection_analysis", {})
            telemetry["council"] = context.get("philosophy", {})
        except Exception as e:
            logger.error(f"Failed to aggregate council data: {e}")
        
        # Telemetry is now purely local for the Sovereign Node
        telemetry["mesh_nodes"]["BATAM_MASTER"] = "ONLINE"
        telemetry["redis"] = "OFFLINE" # Default

        # Check Local Redis
        redis_path = shutil.which("redis-cli")
        if redis_path:
            try:
                proc = await asyncio.create_subprocess_shell(f"{redis_path} ping", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, _ = await proc.communicate()
                if b"PONG" in stdout: telemetry["redis"] = "ONLINE"
            except: pass

        # 3. Intelligent Status Text (For Sovereign Dashboard)
        activity = "Monitoring Sovereign Batam Node."
        difficulty = "None"
        problems = []
        if telemetry["redis"] == "OFFLINE":
            problems.append("Local Redis Offline")
        if telemetry["system_stats"]["BATAM_MASTER"]["ram"] > 90:
            problems.append("High Memory Pressure")
        
        if problems:
            difficulty = ", ".join(problems)
        
        telemetry["status_text"] = {
            "activity": activity,
            "difficulty": difficulty
        }
        telemetry["ai_online"] = True # Assuming Ollama is reachable
        
        return telemetry


    def handle_sigterm(self, signum, frame):
        """Graceful shutdown for Master Node."""
        logger.info(f"👋 Received signal {signum}. Shutting down Sovereign Master...")
        self.is_running = False
        # In a real async app, we'd trigger loop.stop() or similar
        # For now, setting is_running=False will break loops
        sys.exit(0)

    def start(self):
        # Start core loops
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Register signal handlers
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
            except NotImplementedError:
                # Fallback for Windows or environments where add_signal_handler fails
                signal.signal(sig, self.handle_sigterm)

        # Add tasks
        loop.create_task(self.mesh_monitor_loop())
        
        logger.info("🎖️ KiBot Sovereign Master is fully OPERATIONAL.")
        try:
            loop.run_forever()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            loop.close()
            logger.info("Sovereign Node offline.")

    async def shutdown(self):
        """Async shutdown handler."""
        logger.info("👋 Initiating graceful shutdown...")
        self.is_running = False
        # Cancel all running tasks
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for t in tasks: t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        asyncio.get_event_loop().stop()

if __name__ == "__main__":
    master = KiBotMaster()
    master.start()
