#!/usr/bin/env python3
"""
🎖️ KiBot Sovereign High Command (Unified Master Controller)
Batam Master Node - Alpha Entry Point
"""

import os
import sys
import json
import time
import psutil
import socket
import logging
import asyncio
import httpx
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
import uvicorn
from fastapi import FastAPI

# --- PATH CONFIGURATION ---
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

# --- KIBOT CORE IMPORTS ---
from SERVER_BATAM.Support.ki_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from SERVER_BATAM.Core.ki_brain import BrainManager
from SERVER_BATAM.Intelligence.kibot_whatif_engine import simulate_pair
from SERVER_BATAM.Support import dynamic_config
from SERVER_BATAM.Intelligence.kibot_learning_engine import LearningEngine

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] 🎖️ KIBOT - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("KiBotMaster")

# --- CONSTANTS ---
LOCAL_LISTEN_PORT = 9998
FEEDBACK_PORT = 9997
EXECUTOR_IP = "100.122.1.109"  # Singapore Tailscale IP
EXECUTOR_PORT = 9999
SECRET_KEY = "kibot_trinity_secure_node"
CONTROL_SERVICES = ["kibot-orchestrator", "kibot-trinity", "indodax-dashboard-proxy"]

NODES = {
    "SCANNER": {
        "ip": "100.105.139.21", 
        "port": 9991, 
        "services": ["kibot-scanner"]
    },
    "EXECUTOR": {
        "ip": "100.122.1.109", 
        "port": 9991, 
        "services": ["kibot-executor-engine", "kibot-polymarket"]
    }
}

class KiBotMaster:
    def __init__(self):
        self.brain = BrainManager()
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

    # --- PILLAR 1: FULL AUTONOMY (HEALTH MONITORING) ---
    def mesh_health_monitor_loop(self):
        logger.info("🟢 Pulse Check Mesh Active (60s loop)")
        while True:
            for name, cfg in NODES.items():
                try:
                    # Quick ping test
                    res = subprocess.run(["ping", "-c", "1", "-W", "2", cfg['ip']], capture_output=True)
                    new_status = "ONLINE" if res.returncode == 0 else "OFFLINE"
                    
                    if self.mesh_health[name] != new_status:
                        self.mesh_health[name] = new_status
                        icon = "🟢" if new_status == "ONLINE" else "🔴"
                        asyncio.run_coroutine_threadsafe(
                            self.notify_telegram(f"{icon} **MESH ALERT**: {name} is now {new_status}"), 
                            self.loop
                        )
                except: pass
            time.sleep(60)

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
                except Exception as e:
                    logger.error(f"Oracle Error: {e}")
                time.sleep(70) # Skip the current minute
            time.sleep(30)

    # --- PILLAR 3: COMMANDER UI (API FOR ANDROID) ---
    def setup_api_routes(self):
        @self.api_app.get("/")
        async def root():
            return {"status": "ONLINE", "node": "BATAM_MASTER", "mesh": self.mesh_health}

        @self.api_app.get("/state")
        async def get_state():
            return self.get_state_data()

        @self.api_app.get("/pnl")
        async def get_pnl():
            state = self.get_state_data()
            return {
                "daily_pnl_pct": state.get("daily_pnl_pct", 0.0),
                "daily_pnl_idr": state.get("daily_pnl_idr", 0)
            }

    def run_api_server(self):
        logger.info("📱 Commander API Serving on http://0.0.0.0:8080")
        uvicorn.run(self.api_app, host="0.0.0.0", port=8080, log_level="error")

    # --- NODE MANAGEMENT ---
    async def get_node_status(self, name, cfg):
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"http://{cfg['ip']}:{cfg['port']}/status")
                if resp.status_code == 200:
                    data = resp.json()
                    cpu = data['metrics']['cpu']
                    status_icon = "🟢" if data['status'] == "ONLINE" else "🔴"
                    return f"{status_icon} **{name}**: {cpu}% CPU"
                return f"🔴 **{name}**: UNREACHABLE"
        except Exception:
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

        # 1. AI Veto
        try:
            veto_status, veto_reason = self.brain.veto_signal(
                pair=symbol,
                msg_type="SIGNAL",
                regime=s.get('regime', 'UNKNOWN'),
                obi=float(s.get('obi', 0.0))
            )
        except Exception as e:
            logger.error(f"AI Veto Error: {e}")
            return

        if veto_status != "APPROVED":
            logger.info(f"🛡️ VETOED: {symbol} | Reason: {veto_reason}")
            return

        # 2. What-If Engine
        try:
            sim = simulate_pair(symbol, price)
            if sim.get("verdict") == "SKIP":
                logger.info(f"🛡️ MATH_SKIP: {symbol} | EV: {sim.get('expectedValue')}")
                return
        except Exception as e:
            logger.error(f"WhatIf Error: {e}")

        # 3. Execution Dispatch to Singapore
        logger.info(f"🚀 GASS! {symbol} | Executing via Singapore...")
        execution_order = {
            "symbol": symbol,
            "price": price,
            "side": "BUY",
            "brain_reason": f"AI:{veto_reason}",
            "timestamp": datetime.now().isoformat()
        }
        try:
            self.out_sock.sendto(json.dumps(execution_order).encode("utf-8"), (EXECUTOR_IP, EXECUTOR_PORT))
        except Exception as e:
            logger.error(f"Execution Dispatch Failed: {e}")

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
        try:
            async with httpx.AsyncClient() as client:
                await client.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage?chat_id={TELEGRAM_CHAT_ID}&text={msg}&parse_mode=Markdown")
        except: pass

    def get_state_data(self):
        paths = [
            ROOT_DIR / "SERVER_BATAM" / ".state" / "runtime_note.json",
            ROOT_DIR / "state" / "full_system_state.json",
            ROOT_DIR / "state" / "portfolio_state.json",
            ROOT_DIR / "state" / "brain_status.json",
        ]
        for p in paths:
            try:
                if p.exists():
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if data: return data
            except: continue
        return {}

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
        
        # Local
        subprocess.run(["sudo", "systemctl", "start", *CONTROL_SERVICES], check=False)
        # Remote
        await self.send_node_command("SCANNER", "start", "kibot-scanner")
        await self.send_node_command("EXECUTOR", "start", "kibot-executor-engine")
        await self.send_node_command("EXECUTOR", "start", "kibot-polymarket")
        
        await update.message.reply_text("✅ **All Subsystems Activated.**")

    async def stop_all_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.auth_check(update): return
        await update.message.reply_text("🛑 **Global Shutdown Sequence Initiated...**")
        
        # Remote
        await self.send_node_command("SCANNER", "stop", "kibot-scanner")
        await self.send_node_command("EXECUTOR", "stop", "kibot-executor-engine")
        await self.send_node_command("EXECUTOR", "stop", "kibot-polymarket")
        # Local
        subprocess.run(["sudo", "systemctl", "stop", *CONTROL_SERVICES], check=False)
        
        await update.message.reply_text("💤 **All Subsystems Parked.**")

    async def emergency_stop_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.auth_check(update): return
        await update.message.reply_text("🚨 **EMERGENCY STOP TRIGGERED!**")
        await self.stop_all_cmd(update, context)

    # --- RUNNER ---
    def start(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Start Threads
        threading.Thread(target=self.signal_receiver_loop, daemon=True).start()
        threading.Thread(target=self.feedback_listener_loop, daemon=True).start()
        threading.Thread(target=self.mesh_health_monitor_loop, daemon=True).start()
        threading.Thread(target=self.midnight_oracle_loop, daemon=True).start()
        threading.Thread(target=self.run_api_server, daemon=True).start()
        
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
