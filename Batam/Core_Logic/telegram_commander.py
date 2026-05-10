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
        
        # 1. Mesh Topology Formatting
        mesh = data.get("mesh_nodes", {})
        def get_status_emoji(node_name):
            status = mesh.get(node_name, "UNKNOWN")
            return "🟢" if status == "ONLINE" else ("🔴" if status == "OFFLINE" else "⚪")

        # 2. Portfolio Metrics
        portfolio = data.get("portfolio", {})
        equity = portfolio.get("equity_idr", 0)
        pnl = portfolio.get("daily_pnl", "0.0%")
        positions = portfolio.get("active_positions", [])

        # 3. Intelligence Context
        market = data.get("market", {})
        mood = market.get("mood", "NEUTRAL")
        regime = market.get("regime", "UNKNOWN")
        bias = data.get("council", {}).get("core", "CAUTIOUS")

        # 4. Stats
        stats = data.get("stats", {})

        report = (
            f"🛡️ **KIBOT SOVEREIGN STATUS REPORT**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 **Mesh Network Status**\n"
            f"- `BATAM_MASTER`: 🟢 ONLINE\n"
            f"- `SG_SCANNER`:   {get_status_emoji('SINGAPORE_SCANNER')} {mesh.get('SINGAPORE_SCANNER', 'UNKNOWN')}\n"
            f"- `SG_EXECUTOR`:  {get_status_emoji('SINGAPORE_EXECUTOR')} {mesh.get('SINGAPORE_EXECUTOR', 'UNKNOWN')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 **Market Intelligence**\n"
            f"- Mood: **{mood}**\n"
            f"- Regime: `{regime}`\n"
            f"- AI Directive: _{bias}_\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 **Sovereign Portfolio**\n"
            f"- Equity: `Rp{equity:,.0f}`\n"
            f"- Daily PnL: **{pnl}**\n"
            f"- Active Trades: `{len(positions)}` positions\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ **System Performance (24h)**\n"
            f"- Signals Scanned: `{stats.get('total', 0)}` \n"
            f"- Approved: `{stats.get('approved', 0)}` ✅\n"
            f"- Vetoed/Skipped: `{stats.get('vetoed', 0) + stats.get('math_skipped', 0)}` 🛡️\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕒 _Last Updated: {data.get('last_update', 'N/A')}_"
        )
        
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
