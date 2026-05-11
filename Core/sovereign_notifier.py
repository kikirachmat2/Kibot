#!/usr/bin/env python3
import os
import json
import time
import asyncio
import httpx
from pathlib import Path
from datetime import datetime

# Load environment
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

try:
    from Core.Support.ki_config import TELEGRAM_BOT_TOKEN as TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
except ImportError:
    TELEGRAM_TOKEN = os.getenv("KIBOT_TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("KIBOT_TELEGRAM_CHAT_ID")

STATE_FILE = ROOT / "Data" / "State" / "notifier_throttle.json"

class SovereignNotifier:
    def __init__(self, token=TELEGRAM_TOKEN, chat_id=TELEGRAM_CHAT_ID):
        self.token = token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        self.throttle_file = STATE_FILE
        self._ensure_state_dir()

    def _ensure_state_dir(self):
        self.throttle_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.throttle_file.exists():
            self._save_throttle_state({})

    def _load_throttle_state(self):
        try:
            if self.throttle_file.exists():
                return json.loads(self.throttle_file.read_text())
        except Exception:
            pass
        return {}

    def _save_throttle_state(self, state):
        self.throttle_file.write_text(json.dumps(state, indent=2))

    async def send_message(self, text, parse_mode='Markdown'):
        """Base method to send telegram message asynchronously."""
        if not self.token or not self.chat_id:
            print("⚠️ Notifier: Telegram credentials missing.")
            return False
            
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.api_url, json=payload)
                if resp.status_code == 200:
                    return True
                else:
                    print(f"❌ Notifier Error {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"❌ Notifier Exception: {e}")
        return False

    async def send_urgent_alert(self, message, incident_key):
        """Sends an alert only if it hasn't been sent in the last 3600 seconds."""
        state = self._load_throttle_state()
        now = time.time()
        last_sent = state.get(incident_key, 0)

        if now - last_sent < 3600:
            print(f"⌛ Notifier: Alert '{incident_key}' throttled. (Cooldown: {int(3600 - (now - last_sent))}s)")
            return False

        full_msg = f"🚨 **URGENT SYSTEM ALERT**\n\n{message}"
        success = await self.send_message(full_msg)
        
        if success:
            state[incident_key] = now
            self._save_throttle_state(state)
        return success

    async def send_status_reply(self, telemetry):
        """Formats and sends the /status reply."""
        report = self._format_status_template(telemetry)
        return await self.send_message(report)

    def _format_status_template(self, data):
        """The User's specific /status template - EXACT FORMAT."""
        # Current Time WIB
        now_wib = datetime.now().strftime("%H:%M:%S")
        
        # Helper for System Stats Emojis
        def get_stat_emoji(val):
            try:
                v = float(val)
                if v < 70: return "🟢"
                if v < 90: return "🟡"
                return "🔴"
            except: return "🔴"

        # Helper for Financial Emojis (Positive > 0)
        def get_fin_emoji(val):
            try:
                # Remove symbols if string
                if isinstance(val, str):
                    v = float(val.replace('%', '').replace('+', '').replace('Rp', '').replace(',', ''))
                else:
                    v = float(val)
                return "🟢" if v > 0 else "🔴"
            except: return "🔴"

        # 1. Mesh Data
        mesh = data.get("mesh_nodes", {})
        sys_stats = data.get("system_stats", {})
        
        def format_node(node_key, label, emoji_icon):
            status = mesh.get(node_key, "OFFLINE")
            stats = sys_stats.get(node_key, {"cpu": 0, "ram": 0, "disk": 0})
            
            s_emoji = "🟢" if status == "ONLINE" else "🔴"
            c_emoji = get_stat_emoji(stats.get("cpu", 0))
            r_emoji = get_stat_emoji(stats.get("ram", 0))
            d_emoji = get_stat_emoji(stats.get("disk", 0))
            
            return (
                f"{emoji_icon} {label}\n"
                f"{s_emoji} Status: {status.capitalize()}\n"
                f"{c_emoji} CPU   : {stats.get('cpu', 0)}%\n"
                f"{r_emoji} RAM   : {stats.get('ram', 0)}%\n"
                f"{d_emoji} DISK  : {stats.get('disk', 0)}%"
            )

        batam_str = format_node("BATAM_MASTER", "SERVER BATAM", "🖥️")
        scanner_str = format_node("SINGAPORE_SCANNER", "SERVER SCANNER", "📡")
        executor_str = format_node("SINGAPORE_EXECUTOR", "SERVER EXECUTOR", "⚡")

        # 2. System Activity
        status_text = data.get("status_text", {})
        activity = status_text.get("activity", "System is idle/stopped.")
        
        # 3. Indodax Financials
        portfolio = data.get("portfolio", {})
        equity = portfolio.get("equity_idr", 0)
        pnl_val = portfolio.get("pnl_idr", 0)
        ret_pct = portfolio.get("return_pct", 0.0)
        wl_ratio = portfolio.get("wl_ratio", "0W / 0L")
        pnl_emoji = get_fin_emoji(pnl_val)

        indodax_str = (
            f"💰 INDODAX PORTFOLIO\n"
            f"{get_fin_emoji(equity)} Equity: Rp {equity:,.0f}\n"
            f"{pnl_emoji} PnL   : Rp {pnl_val:,.0f} ({ret_pct:+.2f}%)\n"
            f"📊 W/L   : {wl_ratio}\n"
        )
        
        # 3.1 Active Positions Indodax
        active_pos = portfolio.get("active_positions", [])
        if active_pos:
            indodax_str += "\n📦 ACTIVE POSITIONS\n"
            for pos in active_pos:
                indodax_str += f"- {pos.get('coin', '???').upper()}: {float(pos.get('amount', 0)):.4f}\n"

        # 4. Polymarket Financials
        poly = data.get("polymarket", {})
        p_equity = poly.get("equity_idr", 0)
        p_ret = poly.get("return_pct", 0.0)
        p_wl = poly.get("wl_ratio", "0W / 0L")
        
        poly_str = (
            f"🔮 POLYMARKET PERF\n"
            f"{get_fin_emoji(p_equity)} Equity: Rp {p_equity:,.0f}\n"
            f"{get_fin_emoji(p_ret)} Return: {p_ret:+.2f}%\n"
            f"📊 W/L   : {p_wl}\n"
        )
        
        # 4.1 Active Positions Polymarket
        p_active = poly.get("active_positions", [])
        if p_active:
            poly_str += "\n🎲 ACTIVE BETS\n"
            for pos in p_active:
                poly_str += f"- {pos.get('market', '???')}: {pos.get('outcome', '???')}\n"

        template = f"""🤖 KiBot Sovereign
🕒 {now_wib} WIB

━━━━━━━━━━━━━━━━━━━━━━

{batam_str}

{scanner_str}

{executor_str}

💬 Sistem: {activity}

━━━━━━━━━━━━━━━━━━━━━━
🇮🇩 INDODAX

💰 Total Saldo : Rp {equity:,.0f}
{ret_emoji} Return      : {ret_pct:+.2f}%
{pnl_emoji} PnL         : Rp {pnl_val:,.0f}
{wl_emoji} Trade W/L   : {wl_ratio}

📂 Portofolio:
{get_fin_emoji(pnl_today)} • PnL Today : {pnl_today}
{get_fin_emoji(pnl_7d)} • PnL 7d    : {pnl_7d}
{get_fin_emoji(pnl_30d)} • PnL 30d   : {pnl_30d}

📦 Asset Holdings:
{asset_str}

━━━━━━━━━━━━━━━━━━━━━━
🔮 POLYMARKET

💰 Total Saldo : Rp {poly_equity:,.0f}
{get_fin_emoji(poly_ret)} Return      : {poly_ret:+.2f}%
{get_fin_emoji(poly_pnl)} PnL         : Rp {poly_pnl:,.0f}
{get_fin_emoji(poly_wl)} Trade W/L   : {poly_wl}

📂 Portofolio:
{get_fin_emoji(poly.get('pnl_today', 0))} • PnL Today : {poly.get('pnl_today', '+0.00%')}
{get_fin_emoji(poly.get('pnl_7d', 0))} • PnL 7d    : {poly.get('pnl_7d', '+0.00%')}
{get_fin_emoji(poly.get('pnl_30d', 0))} • PnL 30d   : {poly.get('pnl_30d', '+0.00%')}

📦 Asset Holdings:
{poly_asset_str}
━━━━━━━━━━━━━━━━━━━━━━"""
        return template

if __name__ == "__main__":
    # Test block
    async def test():
        notifier = SovereignNotifier()
        mock_data = {
            "mesh_health": "DEGRADED",
            "nodes": {
                "Batam": {"online": True, "cpu": 2.6, "ram": 8.9, "disk": 15.0},
                "Executor": {"online": True, "cpu": 3.6, "ram": 57.5, "disk": 37.5},
                "Scanner": {"online": False, "cpu": 0, "ram": 0, "disk": 0}
            },
            "current_activity": "Node connectivity issues",
            "current_difficulty": "Executor node lag detected"
        }
        print("--- TEST STATUS TEMPLATE ---")
        print(notifier._format_status_template(mock_data))
        # await notifier.send_urgent_alert("Testing Notifier centralisation.", "test_alert")
    
    asyncio.run(test())
