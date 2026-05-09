# --- BOOTSTRAP: Absolute Pathing & Log Rotation ---
import os
import sys
from pathlib import Path
import logging
import signal
from logging.handlers import RotatingFileHandler

# Force absolute pathing to project root
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Load Sovereign Environment (API Keys, etc.)
try:
    from SERVER_BATAM.Support.ki_vault import load_sovereign_env
    load_sovereign_env()
except Exception as e:
    print(f"⚠️ Vault Load Warning: {e}")

# Setup Rotating Logs (Max 10MB per file, keep 5 backups)
log_file = ROOT_DIR / "SERVER_BATAM" / "Logs" / "kibot_master.log"
log_file.parent.mkdir(parents=True, exist_ok=True)
handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
formatter = logging.Formatter('[%(asctime)s] 🎖️ KIBOT - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

logger = logging.getLogger("KiBot")
logger.setLevel(logging.INFO)
logger.addHandler(handler)
logger.addHandler(logging.StreamHandler()) # Also print to console

# --- BOOTSTRAP: Dynamic Imports to prevent Startup Death ---
import time
import json
import asyncio
import threading
import subprocess
import platform
from datetime import datetime
from typing import Dict, List, Optional

try:
    from SERVER_BATAM.Core.ki_brain import BrainManager
except Exception as e:
    print(f"⚠️ Warning: Could not load BrainManager during bootstrap: {e}")
    BrainManager = None

import psutil
import socket
import httpx
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import json

# --- PATH CONFIGURATION ---
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

# --- KIBOT CORE IMPORTS ---
from SERVER_BATAM.Support.ki_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OLLAMA_URL, KiConfig
from SERVER_BATAM.Intelligence.kibot_whatif_engine import simulate_pair
from SERVER_BATAM.Support import dynamic_config
from SERVER_BATAM.Intelligence.kibot_learning_engine import LearningEngine
from SERVER_BATAM.Intelligence.kibot_ai_search import search_web

# Use the global logger configured in the bootstrap section
logger = logging.getLogger("KiBot")

# --- CONSTANTS ---
LOCAL_LISTEN_PORT = 9998
FEEDBACK_PORT = 9997
EXECUTOR_IP = "213.35.118.26"  # Singapore Public IP (Oracle)
EXECUTOR_PORT = 9999
SECRET_KEY = "kibot_trinity_secure_node"
CONTROL_SERVICES = ["kibot-orchestrator", "kibot-trinity", "indodax-dashboard-proxy"]

NODES = {
    "SCANNER": {
        "ip": "152.69.218.198", 
        "port": 9991, 
        "services": ["kibot-scanner-mesh", "kibot-sensory-mesh"]
    },
    "EXECUTOR": {
        "ip": "213.35.118.26", 
        "port": 9991, 
        "services": ["kibot-executor-engine", "kibot-polymarket"]
    }
}

class KiBotMaster:
    def __init__(self):
        # AI Core Initialization
        self.brain = BrainManager() if BrainManager else None
        if not self.brain:
            logger.error("⚠️ CRITICAL: BrainManager is NOT available. KiBot running in DEGRADED MODE (Healer Active).")
        self.running = False
        self.start_time = datetime.now()
        
        # Sockets
        self.in_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.in_sock.bind(("0.0.0.0", LOCAL_LISTEN_PORT))
        self.out_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # State
        self.last_state = {}
        self.mesh_health = {"SCANNER": "UNKNOWN", "EXECUTOR": "UNKNOWN"}

        # Pillar 3: Commander API Setup
        self.api_app = FastAPI()
        self.setup_api_routes()
        
        # Market Sentiment State
        self.market_mood = "NEUTRAL"
        self.last_mood_update = None
        
        # Start Background Pulses (Market Scout)
        threading.Thread(target=self.global_market_pulse_loop, daemon=True).start()
        
        # [NEW] PID Management to prevent Telegram Conflicts
        self.manage_pid()

    def manage_pid(self):
        pid_file = ROOT_DIR / "kibot.pid"
        current_pid = os.getpid()
        if pid_file.exists():
            try:
                old_pid = int(pid_file.read_text().strip())
                if psutil.pid_exists(old_pid) and old_pid != current_pid:
                    logger.warning(f"⚠️ Found legacy KiBot process ({old_pid}). Terminating for clean startup...")
                    os.kill(old_pid, signal.SIGTERM)
                    time.sleep(2)
                    if psutil.pid_exists(old_pid):
                        os.kill(old_pid, signal.SIGKILL)
            except Exception as e:
                logger.error(f"PID cleanup error: {e}")
        
        pid_file.write_text(str(current_pid))
        logger.info(f"🆔 KiBot Master PID: {current_pid}")

    # --- PILLAR 1: FULL AUTONOMY (HEALTH MONITORING) ---
    def mesh_health_monitor_loop(self):
        logger.info("🟢 Pulse Check Mesh Active (60s loop) - SELF-HEALING ENABLED")
        while True:
            for name, cfg in NODES.items():
                try:
                    # Smart Probe via SSH port (since Oracle blocks PING)
                    import socket
                    is_reachable = False
                    try:
                        with socket.create_connection((cfg['ip'], 22), timeout=3):
                            is_reachable = True
                    except:
                        is_reachable = False
                    
                    new_status = "ONLINE" if is_reachable else "OFFLINE"
                    
                    if self.mesh_health.get(name) != new_status:
                        self.mesh_health[name] = new_status
                        icon = "🟢" if new_status == "ONLINE" else "🔴"
                        # Trigger Telegram Alert using threadsafe way
                        msg = f"{icon} **MESH ALERT**: {name} is now {new_status}"
                        try:
                            if hasattr(self, 'loop') and self.loop:
                                asyncio.run_coroutine_threadsafe(self.send_telegram_msg(msg), self.loop)
                        except:
                            pass
                except Exception as e:
                    logger.error(f"Health check failed for {name}: {e}")
            time.sleep(5)
    def global_market_pulse_loop(self):
        """
        Periodically wakes up the 'Scout' (1B) to check global market mood.
        """
        logger.info("🟢 Global Market Pulse Active (30m loop) - SCOUT ENABLED")
        while True:
            try:
                # 1. Search for latest crypto news
                news = search_web("latest crypto market sentiment today btc eth", max_results=5)
                news_text = "\n".join([f"- {n.get('title')}: {n.get('snippet')}" for n in news])

                # 2. Ask the Scout (1B) for a quick mood check
                prompt = f"Analyze these news headlines and return only ONE word: BULLISH, BEARISH, or NEUTRAL. \n\n{news_text}"
                
                payload = {
                    "model": "llama3.2:1b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0}
                }
                
                # Use brain's post helper
                response = self.brain._post_json(f"{OLLAMA_URL}/api/generate", body=payload, timeout=15.0)
                mood = response.get("response", "NEUTRAL").strip().upper()
                
                # Sanitize response to just the keyword
                for valid in ["BULLISH", "BEARISH", "NEUTRAL"]:
                    if valid in mood:
                        self.market_mood = valid
                        break
                
                self.last_mood_update = datetime.now()
                logger.info(f"📊 SCOUT PULSE: Market Mood is now {self.market_mood}")
                
            except Exception as e:
                logger.error(f"Scout pulse failed: {e}")
            
            time.sleep(1800)  # 30 minutes

    def attempt_node_recovery(self, node_name):
        """Proactive recovery for dead nodes with AI Self-Healing Escalation"""
        logger.warning(f"🛠️ Attempting recovery for {node_name}...")
        services = NODES[node_name]["services"]
        for svc in services:
            res = asyncio.run(self.send_node_command(node_name, "start", svc))
            if res.get("ok"):
                logger.info(f"✅ Recovery signal sent to {node_name} for {svc}")
            else:
                logger.error(f"❌ Standard recovery failed for {node_name}. Escalating to THE MECHANIC...")
                self.trigger_ai_healer(node_name, res.get("msg", "Node unreachable"))

    def get_remote_stats(self, node_name):
        """Pulls CPU/RAM/Disk stats from remote node via SSH"""
        try:
            cfg = NODES.get(node_name)
            # Lightweight command to get stats in JSON-like format
            cmd = ["ssh", cfg['ip'], "free -m | awk 'NR==2{printf \"RAM: %s/%sMB \", $3,$2}'; df -h / | awk 'NR==2{printf \"Disk: %s/%s \", $3,$2}'; top -bn1 | grep \"Cpu(s)\" | awk '{printf \"CPU: %s%%\", $2}'"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return res.stdout if res.returncode == 0 else "Stats Unavailable"
        except Exception: return "Oversight Offline"

    def get_remote_logs(self, node_name, tail_lines=100):
        """Autonomous Log Harvester for The Mechanic"""
        try:
            cfg = NODES.get(node_name)
            # Find common log paths
            remote_path = f"/home/ubuntu/KiBot/Logs/{node_name.lower()}.log"
            cmd = ["ssh", cfg['ip'], f"tail -n {tail_lines} {remote_path} || journalctl -u kibot-{node_name.lower()} -n {tail_lines}"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return res.stdout if res.returncode == 0 else f"Fail: {res.stderr}"
        except Exception as e: return f"Error: {e}"

    def trigger_ai_healer(self, node_name, error_msg):
        """
        Escalation path: Use qwen2.5-coder:7b + Aider + Remote Logs to fix bugs.
        """
        try:
            # 1. Gather context from the node
            remote_logs = self.get_remote_logs(node_name)
            remote_stats = self.get_remote_stats(node_name)
            
            # 2. Construct Aider command with full context
            aider_cmd = [
                "/home/ubuntu/.local/bin/aider",
                "--model", "ollama/qwen2.5-coder:7b",
                "--message", f"URGENT REPAIR for {node_name}. \nError: {error_msg}\nStats: {remote_stats}\nLogs: {remote_logs}\nAction: Fix and provide SSH deploy command.",
                "--auto-commit", "--no-show-diffs", "--yes"
            ]
            
            logger.info(f"🤖 MECHANIC: Fixing {node_name} with remote context...")
            def run_fix():
                subprocess.run(aider_cmd, capture_output=True, text=True, timeout=300)
                # After fix, try to push to node (Aider auto-commits locally, we just need to restart node)
                self.attempt_node_recovery(node_name)
            
            threading.Thread(target=run_fix, daemon=True).start()
        except Exception as ex: logger.error(f"⚠️ Healer bridge crashed: {ex}")

    # --- PILLAR 2: SOVEREIGN INTELLIGENCE (MIDNIGHT ORACLE) ---
    def midnight_oracle_loop(self):
        logger.info("🌙 Midnight Oracle Loop Waiting for 00:00...")
        while True:
            now = datetime.now()
            if now.hour == 0 and now.minute == 0:
                logger.info("📜 Executing Midnight Oracle Self-Learning...")
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.notify_telegram("📜 **MIDNIGHT ORACLE**: Analyzing today's performance..."), 
                        self.loop
                    )
                    engine = LearningEngine()
                    result = engine.audit_and_optimize()
                    
                    msg = f"🧠 **ORACLE UPDATE**\n{result.get('summary', 'Optimized.')}"
                    asyncio.run_coroutine_threadsafe(self.notify_telegram(msg), self.loop)
                    
                    # --- NEW: Auto-Backup Vault ---
                    logger.info("💾 Triggering Midnight Vault Backup...")
                    subprocess.run(["python3", "SERVER_BATAM/Support/ki_vault.py", "backup"], capture_output=True)
                except Exception as e:
                    logger.error(f"Oracle Error: {e}")
                time.sleep(70) # Skip the current minute
            time.sleep(30)

    # --- PILLAR 2.1: INFRASTRUCTURE GUARD ---
    async def resource_monitor_loop(self):
        """Autonomous Resource Management: Prevents OOM by unloading AI models"""
        logger.info("🟢 Resource Monitor Active (5m loop) - AUTO-OPTIMIZE ENABLED")
        while True:
            try:
                mem = psutil.virtual_memory()
                if mem.percent > 85:
                    logger.warning(f"⚠️ RAM Critical ({mem.percent}%). Unloading AI Cache...")
                    subprocess.run(["curl", "-X", "POST", f"{OLLAMA_URL}/api/generate", "-d", '{"model": "", "keep_alive": 0}'], capture_output=True)
                
                for node_name, node_data in NODES.items():
                    ip = node_data.get("ip")
                    # Smart Probe: Try KiBot port or SSH
                    is_reachable = False
                    try:
                        with socket.create_connection((ip, node_data.get('port', 9991)), timeout=2):
                            is_reachable = True
                    except:
                        try:
                            with socket.create_connection((ip, 22), timeout=2):
                                is_reachable = True
                        except:
                            is_reachable = False
                    
                    if not is_reachable:
                        logger.error(f"🌐 Mesh Link Broken: {node_name} ({ip}) is unreachable!")
                    else:
                        logger.info(f"🌐 Mesh Link Stable: {node_name} ({ip})")
                
            except Exception as e:
                logger.error(f"Resource monitor error: {e}")
            await asyncio.sleep(300)

    # --- PILLAR 2.2: LIVE HEARTBEAT ---
    async def daily_report_loop(self):
        """Sends a status summary to Telegram every morning at 08:00"""
        logger.info("🟢 Daily Heartbeat Active (Waiting for 08:00)")
        while True:
            now = datetime.now()
            if now.hour == 8 and now.minute == 0:
                try:
                    uptime = datetime.now() - self.start_time
                    msg = f"🎖️ **KiBot Daily Heartbeat**\n⏱️ Uptime: {str(uptime).split('.')[0]}\n🧠 Mood: {self.market_mood}\nStatus: **LIVE** 🟢"
                    await self.send_telegram_msg(msg)
                    time.sleep(70)
                except Exception as e:
                    logger.error(f"Heartbeat error: {e}")
            await asyncio.sleep(30)

    def get_remote_logs(self, node_name, tail_lines=50):
        """Autonomous Log Harvester for The Mechanic"""
        try:
            cfg = NODES.get(node_name)
            remote_path = f"/home/ubuntu/KiBot/Logs/{node_name.lower()}.log"
            cmd = ["ssh", cfg['ip'], f"tail -n {tail_lines} {remote_path}"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return res.stdout if res.returncode == 0 else f"Fail: {res.stderr}"
        except Exception as e: return f"Error: {e}"

    # --- PILLAR 3: COMMANDER UI (API FOR ANDROID) ---
    def setup_api_routes(self):
        @self.api_app.get("/")
        async def root():
            return {"status": "ONLINE", "node": "BATAM_MASTER", "mesh": self.mesh_health}

        @self.api_app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            logger.info("📱 Android Commander Connected via WebSocket")
            try:
                while True:
                    # Stream state data every 2 seconds
                    state_data = self.get_state_data()
                    state_data["mesh"] = self.mesh_health
                    state_data["timestamp"] = datetime.now().isoformat()
                    
                    await websocket.send_json(state_data)
                    
                    # Receive potential commands from APK
                    try:
                        data = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
                        cmd_data = json.loads(data)
                        logger.info(f"📱 Command from APK: {cmd_data}")
                        # Process command (e.g., restart node)
                        if "action" in cmd_data:
                            await self.handle_apk_command(cmd_data)
                    except asyncio.TimeoutError:
                        pass
            except WebSocketDisconnect:
                logger.info("📱 Android Commander Disconnected")

    async def handle_apk_command(self, cmd_data):
        action = cmd_data.get("action")
        target = cmd_data.get("target")
        if action == "restart":
            await self.send_node_command(target, "restart", "kibot-mesh")
            await self.notify_telegram(f"📱 **APK CMD**: Restarting {target}...")

    def run_api_server(self):
        logger.info("📱 Commander API Serving on http://0.0.0.0:8080")
        uvicorn.run(self.api_app, host="0.0.0.0", port=8080, log_level="error")

    # --- NODE MANAGEMENT ---
    async def get_node_status(self, name, cfg):
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                # Try high-level API status
                resp = await client.get(f"http://{cfg['ip']}:{cfg['port']}/status")
                if resp.status_code == 200:
                    data = resp.json()
                    cpu = data['metrics']['cpu']
                    status_icon = "🟢" if data['status'] == "ONLINE" else "🔴"
                    return f"{status_icon} **{name}**: {cpu}% CPU"
        except Exception:
            pass
            
        # Fallback to mesh_health (verified via SSH port 22 in health monitor loop)
        cached_health = self.mesh_health.get(name, "OFFLINE")
        if cached_health == "ONLINE":
            return f"🟢 **{name}**: ONLINE (via Mesh Link)"
        return f"🔴 **{name}**: OFFLINE"

    async def send_node_command(self, node_name, command, service):
        node = NODES.get(node_name.upper())
        if not node: return {"ok": False, "msg": "Node not found"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"http://{node['ip']}:{node['port']}/",
                    json={"key": SECRET_KEY, "command": command, "service": service}
                )
                return resp.json()
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    # --- BRAIN LOGIC (SIGNAL PROCESSING) ---
    def decide_and_execute(self, s):
        symbol = s.get('s') or s.get('base_symbol')
        price = float(s.get('p') or s.get('price_idr') or s.get('price_usdt', 0))
        
        if not symbol or price <= 0: return

        # 1. AI Veto (Fast Path)
        try:
            veto_status, veto_reason = self.brain.veto_signal(
                pair=symbol,
                msg_type=s.get('type', 'SIGNAL'),
                regime=s.get('regime', 'UNKNOWN'),
                obi=float(s.get('obi', 0.0))
            )
        except Exception as e:
            logger.error(f"AI Veto Error: {e}")
            return

        if veto_status != "APPROVED":
            logger.info(f"🛡️ VETOED: {symbol} | Reason: {veto_reason}")
            return

        # 2. What-If Engine (Math Guard)
        try:
            sim = simulate_pair(symbol, price)
            if sim.get("verdict") == "SKIP":
                logger.info(f"🛡️ MATH_SKIP: {symbol} | EV: {sim.get('expectedValue')}")
                return
        except Exception as e:
            logger.error(f"WhatIf Error: {e}")

        # 3. Deep Reasoning (Async Path - Don't block execution but inform next trade)
        self._trigger_deep_reasoning(symbol, price)

        # 4. Execution Dispatch to Singapore
        logger.info(f"🚀 GASS! {symbol} | Executing via Singapore...")
        execution_order = {
            "symbol": symbol,
            "price": price,
            "side": "BUY",
            "brain_reason": f"AI:{veto_reason}",
            "timestamp": datetime.now().isoformat(),
            "meta": s.get("meta", {})
        }
        # Dynamic Routing based on Symbol
        target_port = EXECUTOR_PORT
        if symbol.startswith("POLY:"):
            target_port = 9990 # Polymarket Executor Port
            
        try:
            self.out_sock.sendto(json.dumps(execution_order).encode("utf-8"), (EXECUTOR_IP, target_port))
            logger.info(f"📤 Signal routed to {EXECUTOR_IP}:{target_port} for {symbol}")
        except Exception as e:
            logger.error(f"❌ Failed to route signal: {e}")
            asyncio.run_coroutine_threadsafe(
                self.notify_telegram(f"❌ **EXECUTION ERROR**: Failed to dispatch {symbol} to Singapore!"), 
                self.loop
            )

    def _trigger_deep_reasoning(self, symbol, price):
        """
        [DEEP RESEARCH] Async sentiment and math validation using Llama 3.1 8B.
        Doesn't block the trade but informs the 'Oracle' and 'Brain' for next moves.
        """
        def worker():
            try:
                if not self.brain: return
                logger.info(f"🧠 DEEP REASONING: Analyzing {symbol} in background...")
                prompt = (
                    f"As a sovereign analyst, evaluate {symbol} at {price}. "
                    f"Current Market Mood: {self.market_mood}. "
                    f"Provide 1-sentence strategic guidance for the next trade."
                )
                payload = {
                    "model": "llama3.1:8b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.4}
                }
                response = self.brain._post_json(f"{OLLAMA_URL}/api/generate", body=payload, timeout=30.0)
                advice = response.get("response", "No advice generated.").strip()
                logger.info(f"🧠 ORACLE ADVICE for {symbol}: {advice}")
                
                # Optional: Send to Telegram if it's very important
                if "URGENT" in advice.upper() or "WARNING" in advice.upper():
                    asyncio.run_coroutine_threadsafe(
                        self.notify_telegram(f"🧠 **DEEP REASONING ALERT** ({symbol}):\n{advice}"), 
                        self.loop
                    )
            except Exception as e:
                logger.debug(f"Deep reasoning failed for {symbol}: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def signal_receiver_loop(self):
        logger.info(f"📡 Signal Receiver Active (Port {LOCAL_LISTEN_PORT})")
        while True:
            try:
                data, addr = self.in_sock.recvfrom(65535)
                payload = json.loads(data.decode("utf-8"))
                
                if payload.get("type") == "HEARTBEAT":
                    continue

                signals = payload.get("signals", [])
                if not signals and "s" in payload:
                    signals = [payload]

                for s in signals:
                    threading.Thread(target=self.decide_and_execute, args=(s,), daemon=True).start()

                # Flow Control
                throttle = dynamic_config.get_param("FLOW_THROTTLE_FACTOR", 0.0)
                if throttle > 0: time.sleep(throttle)
            except Exception as e:
                logger.error(f"Receiver Loop Error: {e}")

    def feedback_listener_loop(self):
        """Listen for reports from Singapore"""
        report_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        report_sock.bind(("0.0.0.0", FEEDBACK_PORT))
        logger.info(f"📡 Feedback Listener Active (Port {FEEDBACK_PORT})")
        
        while True:
            try:
                data, addr = report_sock.recvfrom(65535)
                report = json.loads(data.decode("utf-8"))
                
                if report.get("type") == "EXECUTION_REPORT":
                    symbol = report.get("symbol")
                    status = report.get("status")
                    logger.info(f"📬 REPORT FROM SINGAPORE: {symbol} -> {status}")
                    
                    # Forward to Telegram
                    msg = f"🔔 **TRADE REPORT**\nPair: `{symbol}`\nStatus: {'✅ SUCCESS' if status == 'SUCCESS' else '❌ FAILED'}"
                    asyncio.run_coroutine_threadsafe(self.notify_telegram(msg), self.loop)
            except Exception as e:
                logger.error(f"Feedback Listener Error: {e}")

    async def notify_telegram(self, msg):
        """Legacy helper for sending telegram messages"""
        try:
            async with httpx.AsyncClient() as client:
                await client.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage?chat_id={TELEGRAM_CHAT_ID}&text={msg}&parse_mode=Markdown")
        except: pass

    async def send_telegram_msg(self, msg):
        """Modern async alias for notify_telegram"""
        await self.notify_telegram(msg)

    def get_state_data(self):
        """Unified State Aggregator for Android Dashboard"""
        aggregated = {
            "total_equity_idr": 0,
            "daily_pnl_pct": 0,
            "daily_pnl_idr": 0,
            "active_trades": [],
            "last_update": datetime.now().isoformat(),
            "mesh_status": self.mesh_health
        }
        
        # Priority Paths
        paths = [
            ROOT_DIR / "Data" / "State" / "sovereign_state.json",
            ROOT_DIR / "Data" / "State" / "world_model.json",
            ROOT_DIR / "state" / "full_system_state.json",
            ROOT_DIR / "state" / "portfolio_state.json",
            ROOT_DIR / "state" / "brain_status.json",
        ]
        
        for p in paths:
            try:
                if p.exists():
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            # Smart merge
                            for key in ["total_equity_idr", "daily_pnl_pct", "daily_pnl_idr", "active_trades"]:
                                if key in data and data[key]:
                                    aggregated[key] = data[key]
                            # World Model / Sentiment merge
                            if "global_bias" in data: aggregated["bias"] = data["global_bias"]
                            if "fear_greed_index" in data: aggregated["fear_greed"] = data["fear_greed_index"]
            except Exception as e:
                logger.debug(f"State load skip {p}: {e}")
                
        return aggregated

    # --- TELEGRAM HANDLERS ---
    async def auth_check(self, update: Update):
        if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID):
            await update.message.reply_text("❌ Unauthorized Access.")
            return False
        return True

    async def start_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.auth_check(update): return
        keyboard = [
            ['/status', '/health', '/pnl'],
            ['/run_all', '/stop_all', '/ask'],
            ['/emergency_stop']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("🎖️ **KiBot High Command (Unified)**\nBatam Master Controller Active.", reply_markup=reply_markup, parse_mode='Markdown')

    async def status_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.auth_check(update): return
        await update.message.reply_text("⏳ Syncing Mesh Status...")
        
        state = self.get_state_data()
        batam_cpu = psutil.cpu_percent()
        
        # Remote Nodes
        node_reports = []
        for name, cfg in NODES.items():
            report = await self.get_node_status(name, cfg)
            node_reports.append(report)
            
        msg = (
            f"📊 **SYSTEM MESH STATUS**\n\n"
            f"🏰 **BATAM (MASTER)**\n"
            f"• CPU: {batam_cpu}%\n"
            f"• Equity: Rp{state.get('total_equity_idr', 0):,.0f}\n\n"
            f"📡 **REMOTE NODES**\n" + "\n".join(node_reports) + "\n\n"
            f"🛡️ **TRINITY MESH**: SYNCHRONIZED"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')

    async def pnl_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.auth_check(update): return
        state = self.get_state_data()
        msg = (
            "💰 **PNL SUMMARY**\n"
            f"• Today: {state.get('daily_pnl_pct', 0.0):+.2f}%\n"
            f"• Net IDR: Rp{state.get('daily_pnl_idr', 0):,.0f}\n"
            "• Fee: PMK-68 Applied ✅"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')

    async def send_telegram_msg(self, text):
        """Force Delivery via CURL (Resilient to library timeouts)"""
        import shlex
        try:
            cmd = f'curl -s -X POST "https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage" -d chat_id="{TELEGRAM_CHAT_ID}" -d text="{text}" -d parse_mode="Markdown"'
            subprocess.run(shlex.split(cmd), capture_output=True, timeout=15)
        except Exception as e:
            logger.error(f"Telegram CURL failed: {e}")

    async def health_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.auth_check(update): return
        res = subprocess.run(["systemctl", "list-units", "kibot-*", "--all", "--no-legend"], capture_output=True, text=True)
        units = [line.strip() for line in res.stdout.splitlines() if "loaded" in line]
        active = [u for u in units if " active " in u]
        failed = [u for u in units if "failed" in u or "dead" in u]
        report = (
            f"🏥 **LOCAL HEALTH CHECK**\n"
            f"• Total Units: {len(units)}\n"
            f"• Active: 🟢 {len(active)}\n"
            f"• Degraded: 🔴 {len(failed)}\n\n"
            f"**Issues:**\n" + ("\n".join([f"❌ `{u.split()[0]}`" for u in failed[:5]]) or "None ✅")
        )
        await update.message.reply_text(report, parse_mode='Markdown')

    async def ask_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.auth_check(update): return
        from SERVER_BATAM.Core.batam_ghost_agent import GhostAgent
        user_query = " ".join(context.args)
        if not user_query:
            await update.message.reply_text("Tanya apa Bos? Contoh: `/ask apa status arbitrase?`")
            return
        await update.message.reply_text("💀 **Ghost Agent** membedah sistem...")
        agent = GhostAgent()
        response = await agent.chat(user_query)
        await update.message.reply_text(f"🦾 **Response:**\n{response}", parse_mode='Markdown')

    async def run_all_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.auth_check(update): return
        await update.message.reply_text("🚀 **Global Startup Sequence Initiated...**")
        
        # Local (Linux Only fallback)
        try:
            if platform.system() == "Linux":
                subprocess.run(["sudo", "systemctl", "start", *CONTROL_SERVICES], check=False)
        except: pass

        # Remote
        for node_name, cfg in NODES.items():
            for service in cfg.get("services", []):
                await self.send_node_command(node_name, "start", service)
        
        await update.message.reply_text("✅ **All Subsystems Activated.**")

    async def stop_all_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.auth_check(update): return
        await update.message.reply_text("🛑 **Global Shutdown Sequence Initiated...**")
        
        # Remote
        for node_name, cfg in NODES.items():
            for service in cfg.get("services", []):
                await self.send_node_command(node_name, "stop", service)
                
        # Local (Linux Only fallback)
        try:
            if platform.system() == "Linux":
                subprocess.run(["sudo", "systemctl", "stop", *CONTROL_SERVICES], check=False)
        except: pass
        
        await update.message.reply_text("💤 **All Subsystems Parked.**")

    async def emergency_stop_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.auth_check(update): return
        await update.message.reply_text("🚨 **EMERGENCY STOP TRIGGERED!**")
        await self.stop_all_cmd(update, context)

    def verify_mesh_connectivity(self):
        """Pre-flight check for Trinity Mesh connectivity"""
        logger.info("🧪 Running pre-flight mesh diagnostics...")
        for name, cfg in NODES.items():
            ip = cfg['ip']
            try:
                # Test SSH port 22
                with socket.create_connection((ip, 22), timeout=3):
                    logger.info(f"✅ Node {name} ({ip}) - SSH REACHABLE")
            except Exception:
                logger.error(f"❌ Node {name} ({ip}) - SSH UNREACHABLE")

        # Test Ollama
        try:
            with socket.create_connection(("127.0.0.1", 11434), timeout=2):
                logger.info("✅ Local Ollama - REACHABLE")
        except Exception:
            logger.error("❌ Local Ollama - UNREACHABLE")

    # --- RUNNER ---
    def start(self):
        # 0. Kill legacy instances
        self.manage_pid()

        # 1. Clear Telegram Webhook (Avoid Conflict)
        import httpx
        try:
            async def clear_webhook():
                async with httpx.AsyncClient() as client:
                    await client.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook?drop_pending_updates=True")
            asyncio.run(clear_webhook())
        except: pass

        # Run pre-flight checks
        self.verify_mesh_connectivity()

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Start Threads
        threading.Thread(target=self.signal_receiver_loop, daemon=True).start()
        threading.Thread(target=self.feedback_listener_loop, daemon=True).start()
        threading.Thread(target=self.midnight_oracle_loop, daemon=True).start()
        threading.Thread(target=self.run_api_server, daemon=True).start()
        
        # Start Mesh Health Monitor AFTER loop is established
        threading.Thread(target=self.mesh_health_monitor_loop, daemon=True).start()
        
        # New Autonomous Triggers
        threading.Thread(target=lambda: asyncio.run(self.resource_monitor_loop()), daemon=True).start()
        threading.Thread(target=lambda: asyncio.run(self.daily_report_loop()), daemon=True).start()
        
        # Start Telegram
        app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", self.start_cmd))
        app.add_handler(CommandHandler("status", self.status_cmd))
        app.add_handler(CommandHandler("pnl", self.pnl_cmd))
        app.add_handler(CommandHandler("health", self.health_cmd))
        app.add_handler(CommandHandler("ask", self.ask_cmd))
        app.add_handler(CommandHandler("run_all", self.run_all_cmd))
        app.add_handler(CommandHandler("stop_all", self.stop_all_cmd))
        app.add_handler(CommandHandler("emergency_stop", self.emergency_stop_cmd))
        
        # Callback Handlers for Remote Control
        async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            query = update.callback_query
            await query.answer()
            if query.data.startswith("restart_"):
                node = query.data.split("_")[1].upper()
                await query.edit_message_text(text=f"🔄 Restarting {node}...")
                # Logic to send SSH restart command via send_node_command
                await self.send_node_command(node, "restart", "kibot-mesh")
                await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"✅ {node} Restart Signal Sent.")

        app.add_handler(CallbackQueryHandler(callback_handler))
        
        logger.info("🎖️ KiBot High Command is now ONLINE.")
        app.run_polling()

if __name__ == "__main__":
    kibot = KiBotMaster()
    kibot.start()
