#!/usr/bin/env python3
import os
import asyncio
import logging
from pathlib import Path
from datetime import datetime

# Load environment
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

try:
    from Core.Support.ki_config import (
        TELEGRAM_BOT_TOKEN as TELEGRAM_TOKEN,
        TELEGRAM_CHAT_ID,
        KiConfig,
    )
except ImportError:
    TELEGRAM_TOKEN = os.getenv("KIBOT_TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("KIBOT_TELEGRAM_CHAT_ID")
    class _FallbackConfig:
        TELEGRAM_GLOBAL_MIN_INTERVAL_SEC = int(os.getenv("KIBOT_TELEGRAM_MIN_INTERVAL_SEC", "30"))
        TELEGRAM_DEDUPE_WINDOW_SEC = int(os.getenv("KIBOT_TELEGRAM_DEDUPE_WINDOW_SEC", "900"))
        TELEGRAM_INCIDENT_COOLDOWN_SEC = int(os.getenv("KIBOT_TELEGRAM_INCIDENT_COOLDOWN_SEC", "3600"))
        TELEGRAM_CLAIM_TTL_SEC = int(os.getenv("KIBOT_TELEGRAM_CLAIM_TTL_SEC", "30"))
    KiConfig = _FallbackConfig()

from Core.Support.telegram_throttle import telegram_send_async, get_telegram_throttle

logger = logging.getLogger("SovereignNotifier")

class SovereignNotifier:
    def __init__(self, token=TELEGRAM_TOKEN, chat_id=TELEGRAM_CHAT_ID):
        self.token = token
        self.chat_id = chat_id
        self.throttle = get_telegram_throttle()

    async def send_message(
        self,
        text,
        parse_mode='Markdown',
        *,
        incident_key=None,
        channel='general',
        min_interval_sec=None,
        dedupe_window_sec=None,
        incident_cooldown_sec=None,
        claim_ttl_sec=None,
        force=False,
    ):
        """Base method to send telegram message asynchronously."""
        if not self.token or not self.chat_id:
            logger.warning("⚠️ Notifier: Telegram credentials missing.")
            return False

        min_interval_sec = (
            KiConfig.TELEGRAM_GLOBAL_MIN_INTERVAL_SEC if min_interval_sec is None else min_interval_sec
        )
        dedupe_window_sec = (
            KiConfig.TELEGRAM_DEDUPE_WINDOW_SEC if dedupe_window_sec is None else dedupe_window_sec
        )
        incident_cooldown_sec = (
            KiConfig.TELEGRAM_INCIDENT_COOLDOWN_SEC if incident_cooldown_sec is None else incident_cooldown_sec
        )
        claim_ttl_sec = (
            KiConfig.TELEGRAM_CLAIM_TTL_SEC if claim_ttl_sec is None else claim_ttl_sec
        )

        return await telegram_send_async(
            text,
            parse_mode=parse_mode,
            incident_key=incident_key,
            channel=channel,
            min_interval_sec=min_interval_sec,
            dedupe_window_sec=dedupe_window_sec,
            incident_cooldown_sec=incident_cooldown_sec,
            claim_ttl_sec=claim_ttl_sec,
            force=force,
            token=self.token,
            chat_id=self.chat_id,
        )

    async def send_urgent_alert(self, message, incident_key):
        """Sends an alert only if it hasn't been sent in the last 3600 seconds."""
        full_msg = f"🚨 *URGENT SYSTEM ALERT*\n\n{message}"
        return await self.send_message(
            full_msg,
            incident_key=incident_key,
            channel="alerts",
            min_interval_sec=max(30, KiConfig.TELEGRAM_GLOBAL_MIN_INTERVAL_SEC),
            dedupe_window_sec=KiConfig.TELEGRAM_DEDUPE_WINDOW_SEC,
            incident_cooldown_sec=KiConfig.TELEGRAM_INCIDENT_COOLDOWN_SEC,
        )

    async def send_status_reply(self, telemetry):
        """Formats and sends the /status reply."""
        report = self._format_status_template(telemetry)
        return await self.send_message(
            report,
            channel="status",
            min_interval_sec=max(180, KiConfig.TELEGRAM_GLOBAL_MIN_INTERVAL_SEC),
            dedupe_window_sec=KiConfig.TELEGRAM_DEDUPE_WINDOW_SEC,
        )

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
        ret_emoji = get_fin_emoji(ret_pct)
        wl_emoji = "📊"

        pnl_today = portfolio.get("pnl_today", "+0.00%")
        pnl_7d = portfolio.get("pnl_7d", "+0.00%")
        pnl_30d = portfolio.get("pnl_30d", "+0.00%")

        active_pos = portfolio.get("active_positions", [])
        asset_str = ""
        if active_pos:
            for pos in active_pos:
                asset_str += f"• {pos.get('coin', '???').upper()}: {float(pos.get('amount', 0)):.4f}\n"
        else:
            asset_str = "• No active positions"

        # 4. Polymarket Financials
        poly = data.get("polymarket", {})
        poly_equity = poly.get("equity_idr", 0)
        poly_ret = poly.get("return_pct", 0.0)
        poly_pnl = poly.get("pnl_idr", 0)
        poly_wl = poly.get("wl_ratio", "0W / 0L")

        p_active = poly.get("active_positions", [])
        poly_asset_str = ""
        if p_active:
            for pos in p_active:
                poly_asset_str += f"• {pos.get('market', '???')[:20]}: {pos.get('outcome', '???')}\n"
        else:
            poly_asset_str = "• No active bets"

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
