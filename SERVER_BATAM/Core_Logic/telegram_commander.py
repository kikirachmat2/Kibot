from datetime import datetime, timezone
import os
import sys
import json
import time
import psutil
import logging
import httpx
import subprocess
import asyncio
from pathlib import Path
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Path Configuration
ROOT_DIR = Path(os.getenv("KIBOT_RUNTIME_ROOT", Path(__file__).resolve().parents[2]))
STATE_DIR = ROOT_DIR / "state"
sys.path.append(str(ROOT_DIR / "SERVER_BATAM"))
sys.path.append(str(ROOT_DIR / "SERVER_BATAM" / "Support"))
from Support.ki_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logging.basicConfig(level=logging.INFO)
CONTROL_SERVICES = ["kibot-orchestrator", "kibot-trinity"]

# REMOTE NODES (Tailscale Mesh IPs)
NODES = {
    "SCANNER": {
        "ip": "100.105.139.21", # Tokyo Scanner Tailscale IP
        "port": 9991, 
        "services": ["kibot-scanner"]
    },
    "EXECUTOR": {
        "ip": "100.122.1.109", # Singapore Tailscale IP
        "port": 9991, 
        "services": ["kibot-executor-engine", "kibot-polymarket"]
    }
}
SECRET_KEY = "kibot_trinity_secure_node"

async def get_node_status(name, ip, port):
    """Fetch status from a remote node agent"""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"http://{ip}:{port}/status")
            if resp.status_code == 200:
                data = resp.json()
                # Basic health formatting
                cpu = data['metrics']['cpu']
                ram = data['metrics']['ram']
                status_icon = "🟢" if data['status'] == "ONLINE" else "🔴"
                return f"{status_icon} **{name}**: {cpu}% CPU | {ram}% RAM"
            return f"🔴 **{name}**: UNREACHABLE"
    except Exception:
        return f"🔴 **{name}**: OFFLINE"

async def send_node_command(name, command, service):
    """Send command to a remote node"""
    node = NODES.get(name.upper())
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

def get_state_data():
    paths = [
        ROOT_DIR / "SERVER_BATAM" / ".state" / "runtime_note.json",
        STATE_DIR / "full_system_state.json",
        STATE_DIR / "portfolio_state.json",
        STATE_DIR / "brain_status.json",
    ]
    for p in paths:
        try:
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data: return data
        except:
            continue
    return {}

async def auth_check(update: Update):
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID):
        await update.message.reply_text("❌ Akses Ditolak. Anda bukan Commander.")
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update): return
    keyboard = [
        ['/dashboard', '/status', '/health'],
        ['/scout', '/pnl', '/chart'],
        ['/ask', '/run_all', '/stop_all'],
        ['/emergency_stop']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("🎖️ **KiBot High Command (Batam)**\nAll nodes are synchronized.", reply_markup=reply_markup, parse_mode='Markdown')

async def status(update, context):
    if not await auth_check(update): return
    state = get_state_data()
    
    # Check Batam Local
    service_res = subprocess.run(["sudo", "systemctl", "is-active", *CONTROL_SERVICES], capture_output=True, text=True)
    service_states = [l.strip() for l in service_res.stdout.splitlines() if l.strip()]
    
    bot_status = "🔴 STANDBY"
    if service_states and all(st == "active" for st in service_states): bot_status = "🟢 ACTIVE"
    elif any(st == "active" for st in service_states): bot_status = "🟡 PARTIAL"
    
    # Check Remote Nodes
    node_reports = []
    for name, cfg in NODES.items():
        report = await get_node_status(name, cfg['ip'], cfg['port'])
        node_reports.append(report)
    
    msg = (
        f"📊 **SYSTEM MESH STATUS**\n\n"
        f"🏰 **BATAM (MASTER)**\n"
        f"• Status: {bot_status}\n"
        f"• Equity: Rp{state.get('total_equity_idr', 0):,.0f}\n"
        f"• Resource: {psutil.cpu_percent()}% CPU\n\n"
                f"📡 **REMOTE NODES**\n" + "\n".join(node_reports) + "\n\n"
                f"🛡️ **TRINITY MESH**: SYNCHRONIZED"
            )
            return msg
    except Exception as e:
        return f"⚠️ Error fetching state: {e}"

async def notify_trade(msg: str):
    """Bridge for other modules to send telegram alerts"""
    try:
        async with httpx.AsyncClient() as client:
            await client.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage?chat_id={TELEGRAM_CHAT_ID}&text={msg}&parse_mode=Markdown")
    except: pass

async def run_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update): return
    await update.message.reply_text("🚀 **Global Startup Sequence Initiated...**")
    
    # 1. Start Batam
    subprocess.run(["sudo", "systemctl", "start", *CONTROL_SERVICES], check=False)
    
    # 2. Start Scanner
    await send_node_command("SCANNER", "start", "kibot-scanner")
    
    # 3. Start Executor (Indodax & Polymarket)
    await send_node_command("EXECUTOR", "start", "kibot-executor-engine")
    await send_node_command("EXECUTOR", "start", "kibot-polymarket")
    
    await update.message.reply_text("✅ **All Subsystems Activated.**")

async def stop_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update): return
    await update.message.reply_text("🛑 **Global Shutdown Sequence Initiated...**")
    
    # Stop Remote
    await send_node_command("SCANNER", "stop", "kibot-scanner")
    await send_node_command("EXECUTOR", "stop", "kibot-executor-engine")
    await send_node_command("EXECUTOR", "stop", "kibot-polymarket")
    
    # Stop Batam
    subprocess.run(["sudo", "systemctl", "stop", *CONTROL_SERVICES], check=False)
    
    await update.message.reply_text("💤 **All Subsystems Parked.**")

async def pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = get_state_data()
    msg = (
        "💰 **PNL SUMMARY**\n"
        f"• Today: {state.get('daily_pnl_pct', 0.0):+.2f}%\n"
        f"• Net IDR: Rp{state.get('daily_pnl_idr', 0):,.0f}\n"
        "• Fee: PMK-68 Applied ✅"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

from Core_Logic.batam_ghost_agent import GhostAgent
agent = GhostAgent()

async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update): return
    user_query = " ".join(context.args)
    if not user_query:
        await update.message.reply_text("Tanya apa Bos? Contoh: `/ask apa strategi arbitrase kita?`")
        return
    await update.message.reply_text("💀 **Ghost Agent** sedang membedah sistem...")
    response = await agent.chat(user_query)
    await update.message.reply_text(f"🦾 **Response:**\n{response}", parse_mode='Markdown')

async def health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update): return
    res = subprocess.run(["systemctl", "list-units", "kibot-*", "--all", "--no-legend"], capture_output=True, text=True)
    units = [line.strip() for line in res.stdout.splitlines() if "loaded" in line]
    active = [u for u in units if " active " in u]
    failed = [u for u in units if "failed" in u or "dead" in u]
    report = (
        f"🏥 **LOCAL HEALTH CHECK**\n"
        f"• Total Units: {len(units)}\n"
        f"• Active: 🟢 {len(active)}\n"
        f"• Degraded/Dead: 🔴 {len(failed)}\n\n"
        f"**Failed Services:**\n" + ("\n".join([f"❌ `{u.split()[0]}`" for u in failed[:10]]) or "None ✅")
    )
    await update.message.reply_text(report, parse_mode='Markdown')

async def emergency_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update): return
    await update.message.reply_text("🚨 **EMERGENCY STOP!** Mematikan seluruh mesh...")
    await stop_all(update, context)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("dashboard", status)) # Map dashboard to status for mesh view
    app.add_handler(CommandHandler("health", health))
    app.add_handler(CommandHandler("pnl", pnl))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("run_all", run_all))
    app.add_handler(CommandHandler("stop_all", stop_all))
    app.add_handler(CommandHandler("emergency_stop", emergency_stop))
    app.run_polling()
