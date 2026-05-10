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

from Core.sovereign_notifier import SovereignNotifier
notifier = SovereignNotifier()

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
        
        report = notifier._format_status_template(data)
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
