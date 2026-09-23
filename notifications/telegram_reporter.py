"""KiBot V3 — Telegram Reporting and Alerting Engine.

Generates scheduled periodic reports according to the V3 Blueprint:
- Daily Report (08:00 WIB): System health, portfolio NAV, PnL, cash reserve.
- Weekly Report (Monday 00:00 WIB): Performance vs BTC Benchmark.
- Monthly Report (1st of month 08:00 WIB): Full audit, manual events log, DCA metrics.

Ref: [1] Telegram Bot API Specification (2026).
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import aiohttp

WIB = timezone(timedelta(hours=7))


class TelegramReporter:
    """Formats and sends asynchronous Telegram notifications and reports."""

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def format_daily_report(
        self,
        nav_idr: float,
        cost_basis_idr: float,
        pnl_pct: float,
        holdings: Dict[str, float],
        prices: Dict[str, float],
        usdt_reserve_idr: float = 0.0,
        cycle_phase: str = "ACCUMULATE_70_30",
        system_health: str = "HEALTHY",
        ts: Optional[datetime] = None,
    ) -> str:
        """Formats the Daily 08:00 WIB Health & Portfolio snapshot."""
        now_wib = ts or datetime.now(WIB)
        date_str = now_wib.strftime("%Y-%m-%d %H:%M WIB")

        lines = [
            "📊 <b>KIBOT V3 — LAPORAN HARIAN</b>",
            f"<i>{date_str}</i>",
            "",
            f"<b>Status Sistem:</b> {'🟢 ' + system_health if system_health == 'HEALTHY' else '🔴 ' + system_health}",
            f"<b>Strategi:</b> <code>{cycle_phase}</code>",
            "",
            "<b>Ringkasan Portofolio:</b>",
            f"• Total NAV: Rp {nav_idr:,.0f}",
            f"• Modal Masuk: Rp {cost_basis_idr:,.0f}",
            f"• Unrealized PnL: {pnl_pct:+.2f}%",
            "",
            "<b>Alokasi Aset:</b>",
        ]

        for asset, amount in holdings.items():
            price = prices.get(asset, 0.0)
            val = amount * price if asset != "IDR" else amount
            pct = (val / nav_idr * 100.0) if nav_idr > 0 else 0.0
            lines.append(f"• {asset}: Rp {val:,.0f} ({pct:.1f}%)")

        lines.append("")
        lines.append("<i>Akumulasi pasif berjalan otomatis. Mode disiplin aktif.</i>")
        return "\n".join(lines)

    def format_weekly_report(
        self,
        nav_idr: float,
        weekly_pnl_pct: float,
        btc_benchmark_pnl_pct: float,
        ts: Optional[datetime] = None,
    ) -> str:
        """Formats the Weekly Monday 00:00 WIB Performance vs Benchmark report."""
        now_wib = ts or datetime.now(WIB)
        date_str = now_wib.strftime("%Y-%m-%d")

        alpha = weekly_pnl_pct - btc_benchmark_pnl_pct

        lines = [
            "📈 <b>KIBOT V3 — LAPORAN MINGGUAN</b>",
            f"<i>Minggu berakhir: {date_str}</i>",
            "",
            "<b>Kinerja 7 Hari:</b>",
            f"• Portofolio Return: {weekly_pnl_pct:+.2f}%",
            f"• Benchmark (BTC-Only Buy & Hold): {btc_benchmark_pnl_pct:+.2f}%",
            f"• Alpha vs BTC Benchmark: {alpha:+.2f}%",
            f"• Portofolio NAV: Rp {nav_idr:,.0f}",
            "",
            "<b>Strategi Portofolio:</b>",
            "• Alokasi Akumulasi: <code>70% BTC / 30% ETH</code>",
            "• Eksekusi: Pure Buy-Only (Taker Market Order)",
            "",
            "<i>Evaluasi: Portofolio vs benchmark BTC-only buy & hold murni.</i>",
        ]
        return "\n".join(lines)

    def format_monthly_report(
        self,
        total_topup_idr: float,
        nav_idr: float,
        total_invested_idr: float,
        all_time_pnl_pct: float,
        topup_count: int,
        manual_events: List[str],
        ts: Optional[datetime] = None,
    ) -> str:
        """Formats the Monthly 1st 08:00 WIB comprehensive audit report."""
        now_wib = ts or datetime.now(WIB)
        month_str = now_wib.strftime("%B %Y")

        lines = [
            f"🏛️ <b>KIBOT V3 — AUDIT BULANAN ({month_str.upper()})</b>",
            "",
            "<b>Akumulasi Modal:</b>",
            f"• Total Topup Masuk: Rp {total_topup_idr:,.0f} ({topup_count} kali)",
            f"• Total Modal Terdeploy: Rp {total_invested_idr:,.0f}",
            f"• Portofolio NAV: Rp {nav_idr:,.0f}",
            f"• All-Time PnL: {all_time_pnl_pct:+.2f}%",
            "",
            "<b>Log Intervensi / Event Khusus:</b>",
        ]

        if manual_events:
            for ev in manual_events:
                lines.append(f"• {ev}")
        else:
            lines.append("• Tidak ada intervensi manual (100% otonom).")

        lines.append("")
        lines.append("<i>Sistem akumulasi murni 70% BTC / 30% ETH aktif.</i>")
        return "\n".join(lines)

    async def send_message(self, text: str) -> bool:
        """Sends an HTML formatted message to Telegram."""
        if not self.bot_token or not self.chat_id:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    return resp.status == 200
        except Exception:
            return False
