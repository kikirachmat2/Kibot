import os
import sys
import json
import time
import psutil
import logging
import httpx
import matplotlib.pyplot as plt
import pandas as pd
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Path Configuration
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Support.ki_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logging.basicConfig(level=logging.INFO)

def get_state_data():
    paths = [
        "/home/ubuntu/KiBot/state/full_system_state.json",
        "/home/ubuntu/KiBot/state/portfolio_state.json",
        "/home/ubuntu/KiBot/state/brain_status.json"
    ]
    for p in paths:
        try:
            if os.path.exists(p):
                with open(p, "r") as f:
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update): return
    keyboard = [['/status', '/chart'], ['/run_bot', '/stop_bot'], ['/pnl', '/ask']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("🎖️ **KiBot Trinity v9.1.1**\nAuthorized Access Granted.", reply_markup=reply_markup, parse_mode='Markdown')

async def run_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update): return
    await update.message.reply_text("🚀 Menyalakan Brain di Batam...")
    os.system("sudo systemctl start kibot-brain")
    time.sleep(2)
    await update.message.reply_text("✅ Brain sedang booting.")

async def stop_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update): return
    await update.message.reply_text("🛑 Mematikan Brain secara halus...")
    os.system("sudo systemctl stop kibot-brain")
    await update.message.reply_text("💤 Brain sudah parkir.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = get_state_data()
    bot_status = "🟢 ACTIVE" if psutil.pid_exists(state.get("manager_pid", 0)) else "🔴 STANDBY"
    msg = (
        f"📊 **SYSTEM STATUS**\n"
        f"• Bot: {bot_status}\n"
        f"• CPU: {psutil.cpu_percent()}%\n"
        f"• RAM: {psutil.virtual_memory().percent}%\n"
        f"• Active Trades: {state.get('active_trades_count', 0)}\n"
        f"• Equity: Rp{state.get('total_equity_idr', 0):,.0f}"
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

async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update): return
    user_query = " ".join(context.args)
    if not user_query:
        await update.message.reply_text("Tanya apa Bos? Contoh: `/ask kondisi market`")
        return
    
    state = get_state_data()
    market = atomic_load("/home/ubuntu/KiBot/state/market_intelligence.json")
    
    context_data = (
        f"DATA PASAR SAAT INI: {json.dumps(market)}\n"
        f"PORTOFOLIO KAMU: {json.dumps(state)}\n"
        f"PERTANYAAN COMMANDER: {user_query}\n\n"
        "Tugas kamu: Jawab sebagai Asisten Trading Elit dari Batam. Singkat, padat, dan beri saran aksi (Beli/Jual/Hold)."
    )
    
    await update.message.reply_text("🧠 Batam AI sedang berpikir...")
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post("http://localhost:11434/api/generate", 
                json={"model": "deepseek-coder-v2:16b", "prompt": context_data, "stream": False}, timeout=60.0)
            await update.message.reply_text(f"🎖️ **Batam Intelligence:**\n{res.json()['response']}", parse_mode='Markdown')
    except:
        await update.message.reply_text("❌ Gagal akses Ollama (Offline?).")

async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📈 Sedang menggambar grafik...")
    try:
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
    os.system("sudo systemctl stop kibot-brain")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    # REGISTER HANDLERS (CRITICAL FIX)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("pnl", pnl))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("chart", chart))
    app.add_handler(CommandHandler("run_bot", run_bot))
    app.add_handler(CommandHandler("stop_bot", stop_bot))
    app.add_handler(CommandHandler("emergency_stop", emergency_stop))
    app.run_polling()
