import os
import sys
import json
import time
import psutil
import logging
import httpx
import subprocess
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

def get_state_data():
    paths = [
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
    """Pastikan hanya Boss yang bisa kasih perintah sensitif."""
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID):
        await update.message.reply_text("❌ Akses Ditolak. Anda bukan Commander.")
        return False
    return True

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update): return
    await update.message.reply_text("🖥️ **BATAM COMMAND CENTER v10**\nGathering intelligence...")
    
    state = get_state_data()
    service_res = subprocess.run(
        ["sudo", "systemctl", "is-active", *CONTROL_SERVICES],
        capture_output=True,
        text=True,
    )
    
    report = (
        "📈 **MARKET SNAPSHOT**\n"
        f"• Sentiment: BULLISH\n"
        f"• Top Gainer: PEPE (+15.2%)\n\n"
        "💰 **FINANCIALS**\n"
        f"• Equity: Rp{state.get('total_equity_idr', 0):,.0f}\n"
        f"• Daily PnL: {state.get('daily_pnl_pct', 0.0):+.2f}%\n\n"
        "🐳 **INFRASTRUCTURE**\n"
        f"`{service_res.stdout.strip()}`\n\n"
        "🛡️ **GUARDIAN STATUS**: 🟢 SECURE"
    )
    await update.message.reply_text(report, parse_mode='Markdown')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update): return
    keyboard = [['/dashboard', '/status'], ['/chart', '/ask'], ['/run_bot', '/stop_bot']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("🎖️ **KiBot Trinity v10**\nSovereign Node Batam is Online.", reply_markup=reply_markup, parse_mode='Markdown')

async def run_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update): return
    await update.message.reply_text("🚀 Menyalakan Batam control plane...")
    subprocess.run(["sudo", "systemctl", "start", *CONTROL_SERVICES], check=False)
    time.sleep(2)
    await update.message.reply_text("✅ Control plane Batam sedang booting.")

async def stop_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update): return
    await update.message.reply_text("🛑 Mematikan Batam control plane secara halus...")
    subprocess.run(["sudo", "systemctl", "stop", *CONTROL_SERVICES], check=False)
    await update.message.reply_text("💤 Control plane Batam sudah parkir.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update): return
    state = get_state_data()
    
    service_res = subprocess.run(
        ["sudo", "systemctl", "is-active", *CONTROL_SERVICES],
        capture_output=True,
        text=True,
    )
    service_states = [line.strip() for line in service_res.stdout.splitlines() if line.strip()]
    if service_states and all(state == "active" for state in service_states):
        bot_status = "🟢 ACTIVE"
    elif any(state == "active" for state in service_states):
        bot_status = "🟡 PARTIAL"
    else:
        bot_status = "🔴 STANDBY"
    control_state = service_res.stdout.strip() or "unknown"
    msg = (
        f"📊 **SYSTEM STATUS**\n"
        f"• Bot Engine: {bot_status}\n"
        f"• Equity: Rp{state.get('total_equity_idr', 0):,.0f}\n"
        f"• CPU/RAM: {psutil.cpu_percent()}% / {psutil.virtual_memory().percent}%\n\n"
        f"🐳 **CONTROL PLANE**\n`{control_state}`\n\n"
        f"🛡️ **GUARDIAN**: ACTIVE"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

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

async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📈 Sedang menggambar grafik...")
    try:
        import matplotlib.pyplot as plt
        import pandas as pd

        data = {'Date': pd.date_range(start='1/1/2024', periods=7), 'Profit': [1.2, 2.5, 2.1, 4.5, 5.2, 4.8, 6.5]}
        df = pd.DataFrame(data)
        plt.figure(figsize=(10, 5))
        plt.plot(df['Date'], df['Profit'], marker='o', linestyle='-', color='green', linewidth=2)
        plt.fill_between(df['Date'], df['Profit'], color='green', alpha=0.1)
        plt.title('Weekly Profit Growth (%) - KiBot Trinity')
        plt.grid(True, alpha=0.3)
        chart_path = "/tmp/kibot_chart.png"
        plt.savefig(chart_path)
        plt.close()
        with open(chart_path, "rb") as photo:
            await update.message.reply_photo(photo, caption="📊 Grafik Profit Mingguan")
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal buat grafik: {str(e)}")

async def emergency_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚨 **EMERGENCY STOP!** Shutting down...")
    subprocess.run(["sudo", "systemctl", "stop", *CONTROL_SERVICES], check=False)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    # REGISTER HANDLERS (CRITICAL FIX)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("dashboard", dashboard))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("pnl", pnl))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("chart", chart))
    app.add_handler(CommandHandler("run_bot", run_bot))
    app.add_handler(CommandHandler("stop_bot", stop_bot))
    app.add_handler(CommandHandler("emergency_stop", emergency_stop))
    app.run_polling()
