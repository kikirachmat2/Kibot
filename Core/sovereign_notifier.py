#!/usr/bin/env python3
import os
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

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
        WIB,
    )
except ImportError:
    TELEGRAM_TOKEN = os.getenv("KIBOT_TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("KIBOT_TELEGRAM_CHAT_ID")
    WIB = None
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
        parse_mode: Optional[str] = 'Markdown',
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

    async def send_daily_report(self, telemetry=None, *, force=False):
        """Send the concise midnight strategy report. One message, no spam."""
        try:
            from Core.Intelligence.daily_report import build_daily_report

            report = build_daily_report(telemetry)
        except Exception as e:
            logger.warning(f"Daily report builder failed, falling back to status: {e}")
            report = self._format_status_template(telemetry or {})
        day_key = (datetime.now(WIB) if WIB else datetime.now()).strftime("%Y-%m-%d")
        return await self.send_message(
            report,
            parse_mode=None,
            incident_key=f"DAILY_REPORT_{day_key}",
            channel="daily_report",
            min_interval_sec=max(300, KiConfig.TELEGRAM_GLOBAL_MIN_INTERVAL_SEC),
            dedupe_window_sec=23 * 3600,
            incident_cooldown_sec=23 * 3600,
            force=force,
        )

    def _format_status_template(self, data):
        """The User's specific /status template - EXACT FORMAT."""
        # Current Time WIB
        now_wib = (datetime.now(WIB) if WIB else datetime.now()).strftime("%H:%M:%S")
        
        # Helper for System Stats Emojis
        def get_stat_emoji(val):
            try:
                v = float(val)
                if v < 70: return "🟢"
                if v < 90: return "🟡"
                return "🔴"
            except Exception:
                return "⚪"
        # Helper for Financial Emojis (Positive > 0, Negative < 0, Zero = Neutral)
        def get_fin_emoji(val):
            try:
                if isinstance(val, str):
                    v = float(val.replace('%', '').replace('+', '').replace('Rp', '').replace(',', ''))
                else:
                    v = float(val)
                if v > 0:
                    return "🟢"
                elif v < 0:
                    return "🔴"
                else:
                    return "⚪"
            except Exception:
                return "⚪"

        # 1. Mesh Data
        mesh = data.get("mesh_nodes", {})
        sys_stats = data.get("system_stats", {})
        
        def format_node(node_key, label, emoji_icon):
            status = mesh.get(node_key, "OFFLINE")
            stats = sys_stats.get(node_key, {"cpu": 0, "ram": 0, "disk": 0})
            
            s_emoji = "🟢" if status == "ONLINE" else "🔴"
            c_emoji = get_stat_emoji(stats.get("cpu", 0)) if status == "ONLINE" else "⚪"
            r_emoji = get_stat_emoji(stats.get("ram", 0)) if status == "ONLINE" else "⚪"
            d_emoji = get_stat_emoji(stats.get("disk", 0)) if status == "ONLINE" else "⚪"
            
            cpu_val = f"{stats.get('cpu', 0)}%" if status == "ONLINE" else "N/A (Offline)"
            ram_val = f"{stats.get('ram', 0)}%" if status == "ONLINE" else "N/A (Offline)"
            disk_val = f"{stats.get('disk', 0)}%" if status == "ONLINE" else "N/A (Offline)"
            
            return (
                f"{emoji_icon} {label}\n"
                f"{s_emoji} Status: {status.capitalize()}\n"
                f"{c_emoji} CPU   : {cpu_val}\n"
                f"{r_emoji} RAM   : {ram_val}\n"
                f"{d_emoji} DISK  : {disk_val}"
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
        combined_equity = portfolio.get("total_balance_idr", portfolio.get("combined_equity_idr", equity))
        reset_balance = portfolio.get("reset_total_balance_idr", portfolio.get("start_total_equity_idr", 0))
        pnl_val = portfolio.get("daily_return_idr", portfolio.get("daily_pnl_idr", portfolio.get("pnl_idr", 0)))
        ret_pct = portfolio.get("daily_return_pct", portfolio.get("daily_pnl_pct", portfolio.get("return_pct", 0.0)))
        daily_state = portfolio.get("daily_state", {}) if isinstance(portfolio.get("daily_state"), dict) else {}
        try:
            pnl_num = float(pnl_val or 0)
        except Exception:
            pnl_num = 0.0
        try:
            ret_num = float(ret_pct or 0)
        except Exception:
            ret_num = 0.0

        # Sanitize dust balance / zero-trade distortion
        if float(combined_equity or 0) < 10000.0 and abs(pnl_num) < 5000.0:
            daily_color = "FLAT"
            ret_num = 0.0
            pnl_num = 0.0
        else:
            daily_color = str(daily_state.get("color") or ("GREEN" if pnl_num > 0 else "RECOVERY" if pnl_num < 0 else "FLAT")).upper()
        wl_ratio = portfolio.get("wl_ratio", "0W / 0L")
        pnl_emoji = get_fin_emoji(pnl_num)
        ret_emoji = get_fin_emoji(ret_num)
        wl_emoji = "📊"

        pnl_today = portfolio.get("pnl_today", "+0.00%")
        pnl_7d = portfolio.get("pnl_7d", "+0.00%")
        pnl_30d = portfolio.get("pnl_30d", "+0.00%")

        active_pos = portfolio.get("active_positions", [])
        asset_str = ""
        if active_pos:
            for pos in active_pos:
                value_idr = float(pos.get("value_idr", 0) or 0)
                pnl_idr = pos.get("pnl_idr")
                pnl_text = f" | PnL Rp {float(pnl_idr):+,.0f}" if pnl_idr is not None else ""
                asset_str += (
                    f"• {pos.get('coin', '???').upper()}: {float(pos.get('amount', 0)):.4f} "
                    f"≈ Rp {value_idr:,.0f}{pnl_text}\n"
                )
        else:
            asset_str = "• No active positions"

        template = f"""🤖 KiBot Sovereign
🕒 {now_wib} WIB

━━━━━━━━━━━━━━━━━━━━━━

💼 Total Saldo Gabungan : Rp {combined_equity:,.0f}
🎯 Daily State     : {daily_color}

{batam_str}

{scanner_str}

{executor_str}

💬 Sistem: {activity}

━━━━━━━━━━━━━━━━━━━━━━
🇮🇩 INDODAX

💰 Saldo Setelah Reset : Rp {reset_balance:,.0f}
{ret_emoji} PnL Harian %  : {ret_num:+.2f}%
{pnl_emoji} Return Harian : Rp {pnl_num:,.0f}
{wl_emoji} Trade W/L   : {wl_ratio}

📂 Portofolio:
{get_fin_emoji(pnl_today)} • PnL Today : {pnl_today}
{get_fin_emoji(pnl_7d)} • PnL 7d    : {pnl_7d}
{get_fin_emoji(pnl_30d)} • PnL 30d   : {pnl_30d}

📦 Asset Holdings:
{asset_str}
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
