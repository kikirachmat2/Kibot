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
    from Support.ki_config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
except ImportError:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "REDACTED_TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1346696386")

STATE_FILE = ROOT / "Batam" / "Data" / "State" / "notifier_throttle.json"

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
        """The User's specific /status template."""
        # Current Time WIB
        now_wib = datetime.now().strftime("%H:%M:%S")
        
        # 1. Mesh Topology & Stats
        mesh = data.get("mesh_nodes", {})
        sys_stats = data.get("system_stats", {})
        
        # 2. System Status Text
        status_text = data.get("status_text", {})
        activity = status_text.get("activity", "System is idle/stopped.")
        difficulty = status_text.get("difficulty", "None")

        # 3. AI & Mesh Status
        is_mesh_broken = "OFFLINE" in [mesh.get("BATAM_MASTER"), mesh.get("SINGAPORE_EXECUTOR"), mesh.get("SINGAPORE_SCANNER")]
        live_status = "🔴 OFFLINE (MESH BROKEN)" if is_mesh_broken else "🟢 ONLINE"
        ai_status = "🔴 OFFLINE (MESH BROKEN)" if is_mesh_broken else "🟢 ONLINE" # Simplified for now

        def get_node_info(node_key, label, emoji_icon):
            status = mesh.get(node_key, "OFFLINE")
            stats = sys_stats.get(node_key, {"cpu": 0, "ram": 0, "disk": 0})
            
            display_status = status
            if node_key == "SINGAPORE_SCANNER" and status != "ONLINE":
                display_status = "UNREACHABLE"
            
            emoji = "🟢" if status == "ONLINE" else "🔴"
            
            return (
                f"{emoji_icon} {label}:({emoji} {display_status})\n"
                f"cpu: {stats.get('cpu', 0)}%\n"
                f"ram: {stats.get('ram', 0)}%\n"
                f"disk: {stats.get('disk', 0)}%"
            )

        batam_str = get_node_info("BATAM_MASTER", "Batam Master", "🏝️")
        executor_str = get_node_info("SINGAPORE_EXECUTOR", "Executor Engine", "⚡")
        scanner_str = get_node_info("SINGAPORE_SCANNER", "Scanner Senses", "📡")

        # 4. Financials (Indodax & Polymarket)
        portfolio = data.get("portfolio", {})
        equity = portfolio.get("equity_idr", 0)
        pnl_val = portfolio.get("pnl_idr", 0)
        ret_pct = portfolio.get("return_pct", 0.0)
        wl_ratio = portfolio.get("wl_ratio", "0W / 0L")

        template = f"""KIBOT 
🕒 {now_wib} WIB
───────────────────

📈 Live Trading: {live_status}

{batam_str}

{executor_str}

{scanner_str}

🧠 Sistem Status:
• Lagi ngapain: {activity}
• Kesulitannya: {difficulty}

🤖 AI Status: {ai_status}
───────────────────
Indodax

💰 Total Saldo: Rp {equity:,.0f}
💹 Return: {ret_pct:+.2f}%
💵 PnL: Rp {pnl_val:,.0f}
📊 Trade W/L: {wl_ratio}

📂 Portofolio:
• PnL Today: {portfolio.get('pnl_today', '+0.00%')}
• PnL 7d: {portfolio.get('pnl_7d', '+0.00%')}
• PnL 30d: {portfolio.get('pnl_30d', '+0.00%')}

📦 Asset Holdings:
{'No active positions' if not portfolio.get('active_positions') else '\\n'.join(portfolio.get('active_positions'))}
───────────────────
Polymarket

💰 Total Saldo: Rp 0
💹 Return: +0.00%
💵 PnL: Rp 0
📊 Trade W/L: 0W / 0L

📂 Portofolio:
• PnL Today: +0.00%
• PnL 7d: +0.00%

📦 Asset Holdings:
No active positions
───────────────────"""
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
