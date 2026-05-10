#!/usr/bin/env python3
import logging
import os
import json
import sys
import asyncio
from pathlib import Path
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Pathing setup to find Support modules
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
PROJECT_ROOT = ROOT_DIR.parent
sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(PROJECT_ROOT / "Support"))

# Core Snap Path
SNAP_PATH = ROOT_DIR / "State" / "telemetry_snapshot.json"

# Load Env (Dynamic from Support)
try:
    from Support.ki_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
except ImportError:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Configure Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(ROOT_DIR / "Logs" / "telegram_commander.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("TelegramCommander")

def format_status_report(data: dict) -> str:
    """Formats the telemetry data into the user's preferred template."""
    # 1. Mesh Topology & Stats
    mesh = data.get("mesh_nodes", {})
    sys_stats = data.get("system_stats", {})
    
    def get_node_info(node_key):
        status = mesh.get(node_key, "OFFLINE")
        stats = sys_stats.get(node_key, {"cpu": 0, "ram": 0, "disk": 0})
        
        if node_key == "BATAM_MASTER":
            emoji = "🟢" if status == "ONLINE" else "🔴"
            return f"🏝️ Batam Master:({emoji} {status})\ncpu: {stats.get('cpu', 0)}%\nram: {stats.get('ram', 0)}%\ndisk: {stats.get('disk', 0)}%"
        
        if node_key == "SINGAPORE_EXECUTOR":
            emoji = "🟢" if status == "ONLINE" else "🔴"
            return f"⚡ Executor Engine ({emoji} {status}):\ncpu: {stats.get('cpu', 0)}%\nram: {stats.get('ram', 0)}%\ndisk: {stats.get('disk', 0)}%"

        if node_key == "SINGAPORE_SCANNER":
            # Template uses "UNREACHABLE" for scanner
            display_status = "ONLINE" if status == "ONLINE" else "UNREACHABLE"
            emoji = "🟢" if status == "ONLINE" else "🔴"
            return f"📡 Scanner Senses ({emoji} {display_status}):\ncpu: {stats.get('cpu', 0)}%\nram: {stats.get('ram', 0)}%\ndisk: {stats.get('disk', 0)}%"

    # 2. Portfolio Metrics (Indodax)
    portfolio = data.get("portfolio", {})
    equity = portfolio.get("equity_idr", 0)
    pnl_val = portfolio.get("pnl_idr", 0)
    ret_pct = portfolio.get("return_pct", 0.0)
    wl_ratio = portfolio.get("wl_ratio", "0W / 0L")
    
    # 3. System Status Text
    status_text = data.get("status_text", {})
    activity = status_text.get("activity", "System is idle/stopped.")
    difficulty = status_text.get("difficulty", "None")

    # 4. AI & Mesh Status
    is_mesh_broken = "OFFLINE" in [mesh.get("BATAM_MASTER"), mesh.get("SINGAPORE_EXECUTOR"), mesh.get("SINGAPORE_SCANNER")]
    live_status = "🔴 OFFLINE (MESH BROKEN)" if is_mesh_broken else "🟢 ONLINE"
    ai_status = "🟢 ONLINE" if data.get("ai_online", True) and not is_mesh_broken else "🔴 OFFLINE (MESH BROKEN)"
    
    # Current Time WIB
    now_wib = datetime.now().strftime("%H:%M:%S")

    return (
        f"KIBOT \n"
        f"🕒 {now_wib} WIB\n"
        f"───────────────────\n\n"
        f"📈 Live Trading: {live_status}\n\n"
        f"{get_node_info('BATAM_MASTER')}\n\n"
        f"{get_node_info('SINGAPORE_EXECUTOR')}\n\n"
        f"{get_node_info('SINGAPORE_SCANNER')}\n\n"
        f"🧠 Sistem Status:\n"
        f"• Lagi ngapain: {activity}\n"
        f"• Kesulitannya: {difficulty}\n\n"
        f"🤖 AI Status: {ai_status}\n"
        f"───────────────────\n"
        f"Indodax\n\n"
        f"💰 Total Saldo: Rp {equity:,.0f}\n"
        f"💹 Return: {ret_pct:+.2f}%\n"
        f"💵 PnL: Rp {pnl_val:,.0f}\n"
        f"📊 Trade W/L: {wl_ratio}\n\n"
        f"📂 Portofolio:\n"
        f"• PnL Today: {portfolio.get('pnl_today', '+0.00%')}\n"
        f"• PnL 7d: {portfolio.get('pnl_7d', '+0.00%')}\n"
        f"• PnL 30d: {portfolio.get('pnl_30d', '+0.00%')}\n\n"
        f"📦 Asset Holdings:\n"
        f"{'No active positions' if not portfolio.get('active_positions') else '\\n'.join(portfolio.get('active_positions'))}\n"
        f"───────────────────\n"
        f"Polymarket\n\n"
        f"💰 Total Saldo: Rp 0\n"
        f"💹 Return: +0.00%\n"
        f"💵 PnL: Rp 0\n"
        f"📊 Trade W/L: 0W / 0L\n\n"
        f"📂 Portofolio:\n"
        f"• PnL Today: +0.00%\n"
        f"• PnL 7d: +0.00%\n"
        f"• PnL 30d: +0.00%\n\n"
        f"📦 Asset Holdings:\n"
        f"No active positions\n"
        f"───────────────────"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /status command."""
    chat_id = str(update.effective_chat.id)
    if TELEGRAM_CHAT_ID and chat_id != str(TELEGRAM_CHAT_ID):
        logger.warning(f"Unauthorized access attempt from Chat ID: {chat_id}")
        await update.message.reply_text("⛔ **Unauthorized Sovereign Request.**\nThis incident has been logged.")
        return

    if not SNAP_PATH.exists():
        await update.message.reply_text("⌛ **Telemetry snapshot not found.**\nMaster Node might be initializing or offline.")
        return

    try:
        with open(SNAP_PATH, "r") as f:
            data = json.load(f)
        
        report = format_status_report(data)
        await update.message.reply_text(report, parse_mode='Markdown')
        logger.info(f"Status report dispatched to {chat_id}")
        
    except Exception as e:
        logger.error(f"Error generating status report: {e}")
        await update.message.reply_text(f"❌ **Sovereign Error**: Failed to read telemetry snapshot.\n`{str(e)[:100]}`")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greeting command."""
    await update.message.reply_text(
        "🎖️ **KiBot Sovereign Command Interface Active.**\n"
        "Authorized access only.\n\n"
        "Available Commands:\n"
        "/status - Full system telemetry snapshot"
    )

if __name__ == '__main__':
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("KIBOT_TELEGRAM_TOKEN is missing from environment!")
        sys.exit(1)
        
    logger.info("Initializing Telegram Commander...")
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('status', status))
    
    logger.info("🚀 Sovereign Command Polling Started.")
    application.run_polling()
