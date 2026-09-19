"""
KiBot V2 — Daily & Weekly Telegram Reporter.
Sends consolidated 00:00 WIB (17:00 UTC) performance report to Telegram.
Format conforms strictly to the Sovereign Multi-Variant Paper Trading specification.
Persists historical snapshots to storage/weekly_reports/YYYY-MM-DD.json.
Retries up to 3 times upon transient network failures.
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

import aiohttp
from config import settings

logger = logging.getLogger("KiBotV2.WeeklyReporter")

INDONESIAN_DAYS = {
    0: "Senin",
    1: "Selasa",
    2: "Rabu",
    3: "Kamis",
    4: "Jumat",
    5: "Sabtu",
    6: "Minggu",
}

INDONESIAN_MONTHS = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}

class WeeklyReporter:
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        reports_dir: Optional[Path] = None,
        start_date: Optional[str] = None,
        audit_cycle_days: int = 14,
    ):
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or settings.TELEGRAM_CHAT_ID
        self.reports_dir = reports_dir or (settings.STATE_DIR / "weekly_reports")
        self.audit_cycle_days = audit_cycle_days
        # Start date baseline for Day {N}
        env_week_start = os.getenv("PAPER_TRADE_WEEK_START", "")
        if env_week_start:
            try:
                # E.g. "2026-09-21T00:00:00+07:00"
                self.start_date_str = env_week_start.split("T")[0]
            except Exception:
                self.start_date_str = start_date or "2026-09-21"
        else:
            self.start_date_str = start_date or "2026-09-21"

        self._running = False
        self._task: Optional[asyncio.Task] = None

    def should_dispatch_report(self, now_dt: Optional[datetime] = None) -> tuple[bool, str]:
        """
        Determines whether 00:00 WIB daily report should fire or skip:
        - If now == first Monday (baseline_week_start 00:00 WIB): SKIP (trading just started).
        - If now == subsequent Monday 00:00 WIB: SEND (Report 7 closing week).
        - If now == Tuesday..Sunday 00:00 WIB: SEND (Reports 1-6).
        """
        dt_wib = now_dt or datetime.now(timezone(timedelta(hours=7)))
        base_dt = datetime.strptime(self.start_date_str, "%Y-%m-%d").date()
        today = dt_wib.date()

        # If today is before baseline date, skip
        if today < base_dt:
            return False, f"skip_before_baseline ({today} < {base_dt})"

        # If today is exactly the first Monday baseline date
        if today == base_dt and dt_wib.weekday() == 0:
            return False, f"skip_first_monday_baseline ({today} is start of week)"

        return True, "send_report"

    def get_day_number(self, target_dt: Optional[datetime] = None) -> int:
        now_dt = target_dt or datetime.now(timezone(timedelta(hours=7)))
        base_dt = datetime.strptime(self.start_date_str, "%Y-%m-%d").date()
        diff_days = (now_dt.date() - base_dt).days + 1
        return max(1, diff_days)

    def get_deadline_info(self, target_dt: Optional[datetime] = None) -> tuple[int, str]:
        now_dt = target_dt or datetime.now(timezone(timedelta(hours=7)))
        base_dt = datetime.strptime(self.start_date_str, "%Y-%m-%d").date()
        end_date = base_dt + timedelta(days=self.audit_cycle_days)
        remaining_days = max(0, (end_date - now_dt.date()).days)
        formatted_end = f"{end_date.day} {INDONESIAN_MONTHS.get(end_date.month, '')} {end_date.year}"
        return remaining_days, formatted_end

    def format_money(self, val: float, with_sign: bool = False) -> str:
        sign = "+" if (with_sign and val > 0) else ("-" if val < 0 else ("+" if with_sign else ""))
        abs_val = abs(val)
        return f"{sign}Rp {abs_val:,.0f}".replace(",", ".")

    def format_pct(self, val: float) -> str:
        sign = "+" if val > 0 else ("-" if val < 0 else "")
        return f"{sign}{abs(val):.2f}%"

    def build_report_message(
        self,
        summary: Dict[str, Any],
        now_wib: Optional[datetime] = None,
        yesterday_equity: Optional[float] = None,
    ) -> str:
        now_dt = now_wib or datetime.now(timezone(timedelta(hours=7)))
        day_n = self.get_day_number(now_dt)
        day_name = INDONESIAN_DAYS.get(now_dt.weekday(), "Hari")
        month_name = INDONESIAN_MONTHS.get(now_dt.month, "")
        date_str = f"{now_dt.day} {month_name} {now_dt.year}"

        # Aggregate total across active variants (P1-P5)
        variant_keys = ["P1", "P2", "P3", "P4", "P5"]
        variant_entries = [summary[k] for k in variant_keys if k in summary and isinstance(summary[k], dict)]
        if not variant_entries:
            variant_entries = [v for k, v in summary.items() if isinstance(v, dict) and "equity_idr" in v]

        total_start_week = sum(v.get("week_start_equity_idr", 100_000.0) for v in variant_entries)
        total_current_eq = sum(v.get("equity_idr", 100_000.0) for v in variant_entries)
        total_initial = sum(100_000.0 for _ in variant_entries) or 500_000.0

        # Cumulative PnL across active variants
        cum_pnl = total_current_eq - total_initial
        cum_pnl_pct = (cum_pnl / total_initial * 100.0) if total_initial > 0 else 0.0

        # Day PnL
        prev_eq = yesterday_equity if yesterday_equity is not None else total_start_week
        day_pnl = total_current_eq - prev_eq
        day_pnl_pct = (day_pnl / prev_eq * 100.0) if prev_eq > 0 else 0.0

        p1_pnl = summary.get("P1", {}).get("cum_pnl_idr", 0.0)
        p2_pnl = summary.get("P2", {}).get("cum_pnl_idr", 0.0)
        p3_pnl = summary.get("P3", {}).get("cum_pnl_idr", 0.0)
        p4_pnl = summary.get("P4", {}).get("cum_pnl_idr", 0.0)
        p5_pnl = summary.get("P5", {}).get("cum_pnl_idr", 0.0)

        # Extract regime details
        regime_val = summary.get("_regime_info", {}).get("regime") or summary.get("P5", {}).get("regime")
        if hasattr(regime_val, "value"):
            regime_str = regime_val.value.upper()
        elif regime_val:
            regime_str = str(regime_val).upper()
        else:
            regime_str = "RANGE"

        btcd_trend = summary.get("_regime_info", {}).get("btc_dominance_trend_7h")
        if btcd_trend is None:
            btcd_trend = summary.get("P5", {}).get("btc_dominance_trend_7h", 0.0)

        deadline_days, deadline_date = self.get_deadline_info(now_dt)

        msg = (
            f"📊 KiBOT V2 — LAPORAN HARI KE-{day_n}\n"
            f"📅 {day_name}, {date_str}\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Modal Awal Minggu: {self.format_money(total_start_week)}\n"
            f"📈 PnL Hari Ini: {self.format_money(day_pnl, with_sign=True)} ({self.format_pct(day_pnl_pct)})\n"
            f"📊 PnL Kumulatif: {self.format_money(cum_pnl, with_sign=True)} ({self.format_pct(cum_pnl_pct)})\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 VARIAN PAPER TRADE:\n"
            f"┌─ P1 Conservative: {self.format_money(p1_pnl, with_sign=True)}\n"
            f"├─ P2 Balanced: {self.format_money(p2_pnl, with_sign=True)}\n"
            f"├─ P3 Aggressive: {self.format_money(p3_pnl, with_sign=True)}\n"
            f"├─ P4 Vol Anomaly: {self.format_money(p4_pnl, with_sign=True)}\n"
            f"└─ P5 Rotation: {self.format_money(p5_pnl, with_sign=True)}\n\n"
            f"📊 REGIME SAAT INI: {regime_str} | BTC.D Trend: {self.format_pct(btcd_trend)}\n\n"
            f"🎯 Deadline: {deadline_days} hari lagi ({deadline_date})"
        )
        return msg

    async def send_telegram_raw(self, message: str, retries: int = 3) -> bool:
        """Sends markdown formatted message to configured Telegram chat with retries."""
        if not self.bot_token or not self.chat_id:
            logger.warning("[WeeklyReporter] Telegram token/chat_id not configured. Printing message to log:")
            logger.info("\n" + message)
            return False

        from notifications.telegram_notifier import telegram_notifier
        if not telegram_notifier.is_chat_id_allowed(self.chat_id):
            logger.warning(f"[WeeklyReporter] BLOCKED unauthorized chat_id: {self.chat_id}")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        # Convert simple text symbols for clean Telegram dispatch
        html_text = (
            message.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        payload["text"] = html_text

        timeout = aiohttp.ClientTimeout(total=10.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(1, retries + 1):
                try:
                    async with session.post(url, json=payload) as resp:
                        if resp.status == 200:
                            logger.info(f"[WeeklyReporter] ✅ Daily report successfully delivered to Telegram (attempt {attempt}).")
                            return True
                        else:
                            body = await resp.text()
                            logger.warning(f"[WeeklyReporter] Telegram HTTP {resp.status} (attempt {attempt}/{retries}): {body}")
                except Exception as exc:
                    logger.warning(f"[WeeklyReporter] Connection error on attempt {attempt}/{retries}: {exc}")

                if attempt < retries:
                    await asyncio.sleep(2.0 * attempt)

        logger.error("[WeeklyReporter] ❌ Failed to deliver report after 3 attempts.")
        return False

    def save_snapshot(self, summary: Dict[str, Any], date_str: str) -> Path:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.reports_dir / f"{date_str}.json"
        snapshot = {
            "date": date_str,
            "timestamp": time.time(),
            "summary": summary,
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
        logger.info(f"[WeeklyReporter] 💾 Saved report snapshot to {file_path}")
        return file_path

    def get_yesterday_equity(self, today_wib: datetime) -> Optional[float]:
        yesterday = today_wib - timedelta(days=1)
        y_str = yesterday.strftime("%Y-%m-%d")
        file_path = self.reports_dir / f"{y_str}.json"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                summary_data = data.get("summary", {})
                variant_keys = ["P1", "P2", "P3", "P4", "P5"]
                filtered_vals = [
                    v.get("equity_idr", 100_000.0)
                    for k, v in summary_data.items()
                    if k in variant_keys and isinstance(v, dict)
                ]
                if filtered_vals:
                    return sum(filtered_vals)
                return sum(v.get("equity_idr", 100_000.0) for v in summary_data.values() if isinstance(v, dict) and "equity_idr" in v)
            except Exception:
                pass
        return None

    async def dispatch_daily_report(self, summary: Dict[str, Any]) -> bool:
        now_wib = datetime.now(timezone(timedelta(hours=7)))
        today_str = now_wib.strftime("%Y-%m-%d")
        y_eq = self.get_yesterday_equity(now_wib)

        msg = self.build_report_message(summary, now_wib=now_wib, yesterday_equity=y_eq)
        self.save_snapshot(summary, today_str)
        return await self.send_telegram_raw(msg)

    async def _schedule_loop(self, paper_runner_fn) -> None:
        """Runs daily at 00:00:05 WIB (17:00:05 UTC)."""
        logger.info("[WeeklyReporter] ⏰ Daily Telegram reporter background scheduler active.")
        while self._running:
            now_utc = datetime.now(timezone.utc)
            # Next target is 17:00:05 UTC (00:00:05 WIB)
            target_utc = now_utc.replace(hour=17, minute=0, second=5, microsecond=0)
            if now_utc >= target_utc:
                target_utc += timedelta(days=1)

            sleep_seconds = (target_utc - now_utc).total_seconds()
            logger.info(f"[WeeklyReporter] Next 00:00 WIB report scheduled in {sleep_seconds/3600:.2f} hours.")
            await asyncio.sleep(sleep_seconds)

            if not self._running:
                break

            try:
                now_wib = datetime.now(timezone(timedelta(hours=7)))
                should_send, reason = self.should_dispatch_report(now_wib)
                if not should_send:
                    logger.info(f"[WeeklyReporter] ⏭️ Skipping scheduled report ({reason}).")
                    continue

                item = paper_runner_fn()
                summary = {}
                if isinstance(item, tuple):
                    p_run, r_run = item
                    if hasattr(p_run, "get_summary"):
                        summary.update(p_run.get_summary())
                    if hasattr(r_run, "get_summary"):
                        p5_sum = r_run.get_summary()
                        summary["P5"] = p5_sum
                        summary["_regime_info"] = {
                            "regime": p5_sum.get("regime", "RANGE"),
                            "btc_dominance_trend_7h": p5_sum.get("btc_dominance_trend_7h", 0.0),
                        }
                elif isinstance(item, dict):
                    summary = item
                elif hasattr(item, "get_summary"):
                    summary = item.get_summary()

                if summary:
                    await self.dispatch_daily_report(summary)
            except Exception as e:
                logger.error(f"[WeeklyReporter] Error during scheduled report dispatch: {e}", exc_info=True)

    def start(self, paper_runner_fn) -> None:
        self._running = True
        self._task = asyncio.create_task(self._schedule_loop(paper_runner_fn))

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

weekly_reporter = WeeklyReporter()
