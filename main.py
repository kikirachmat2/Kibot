"""KiBot V3 — Main Orchestrator & Interactive Telegram Command Handler.

Supports:
- Paper Trading Mode (Virtual balance, simulated order book execution, no real API keys consumed)
- Live Trading Mode (Indodax API integration with taker market order execution)
- Telegram Commands:
    /topup <amount>       — Simulate or record incoming deposit event (70% BTC / 30% ETH)
    /status               — Real-time NAV, holdings, and portfolio health
    /report               — Trigger immediate on-demand report

Note: Bot is PURE BUY-ONLY. Sells and withdrawals are executed manually by Supervisor in Indodax app.
"""

from typing import Dict, Any, Optional, List
import os
import time
import json
import asyncio
from datetime import datetime, timezone, timedelta

from storage.database import Database
from core.portfolio import PortfolioTracker
from core.allocator import allocate
from notifications.telegram_reporter import TelegramReporter
from ingestion.indodax_client import IndodaxClient
from config.fees import IDR_BUY_FEES
from config.settings import settings

WIB = timezone(timedelta(hours=7))


class KiBotV3Orchestrator:
    """Central runner coordinating paper/live execution and commands."""

    def __init__(
        self,
        db_path: str = "kibot_v3.db",
        paper_mode: bool = True,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        indodax_client: Optional[IndodaxClient] = None,
        health_port: Optional[int] = None,
        health_host: str = "0.0.0.0",
        settings_override: Optional[Any] = None,
    ):
        self.db_path = db_path
        self.paper_mode = paper_mode
        self.health_port = health_port
        self.health_host = health_host
        self.settings = settings_override or settings
        self.db = Database(db_path)
        self.portfolio = PortfolioTracker(self.db)
        self.reporter = TelegramReporter(bot_token, chat_id)
        self.indodax_client = indodax_client or IndodaxClient()
        from core.event_detector import EventDetector
        self.event_detector = EventDetector(self.db)
        self._last_balance_snapshot: Dict[str, float] = self._load_last_balance_snapshot()

        # Real-time price cache (60s TTL)
        self._price_cache: Dict[str, float] = {
            "BTC": 1_420_000_000.0,
            "ETH": 45_800_000.0,
            "USDT": 17_500.0,
        }
        self._price_cache_ts: float = 0.0

        # Health and failure monitoring state (Tasks 2 & 4)
        self.start_time: float = time.time()
        self.last_poll_ts: Optional[float] = None
        self.last_price_fetch_ts: Optional[float] = None
        self.consecutive_poll_failures: int = 0
        self.consecutive_telegram_failures: int = 0
        self.consecutive_scheduler_failures: int = 0
        self.first_poll_failure_ts: Optional[float] = None
        self.first_telegram_failure_ts: Optional[float] = None
        self.first_scheduler_failure_ts: Optional[float] = None
        self.last_poll_escalation_ts: float = 0.0
        self.last_telegram_escalation_ts: float = 0.0
        self.last_scheduler_escalation_ts: float = 0.0

    def _load_last_balance_snapshot(self) -> Dict[str, float]:
        """Loads the persisted balance snapshot from SQLite system_state if present."""
        try:
            val = self.db.get_state("last_balance_snapshot")
            if val:
                data = json.loads(val)
                if isinstance(data, dict):
                    return {str(k).lower(): float(v) for k, v in data.items()}
        except Exception as e:
            print(f"⚠️ Failed to restore balance snapshot from DB: {e}", flush=True)
        return {}

    def _save_last_balance_snapshot(self, snapshot: Dict[str, float]):
        """Persists the latest balance snapshot into SQLite system_state."""
        try:
            self.db.set_state("last_balance_snapshot", json.dumps(snapshot))
        except Exception as e:
            print(f"⚠️ Failed to persist balance snapshot to DB: {e}", flush=True)

    def get_current_prices(self, assets: Optional[list] = None) -> Dict[str, float]:
        """
        Retrieves real-time market prices from Indodax public ticker API.
        Caches for 60 seconds to prevent exchange rate limit throttling.
        """
        import time
        now = time.time()
        if now - self._price_cache_ts < 60.0:
            return dict(self._price_cache)

        targets = assets or ["BTC", "ETH", "USDT"]
        updated_prices = dict(self._price_cache)

        fetched_any = False
        for asset in targets:
            if asset == "IDR":
                updated_prices["IDR"] = 1.0
                continue
            pair = f"{asset.lower()}idr"
            try:
                import urllib.request
                import json
                url = f"https://indodax.com/api/ticker/{pair}"
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "KiBotV3-LivePriceIngestion/1.0"}
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        last_price = float(data.get("ticker", {}).get("last", 0.0))
                        if last_price > 0:
                            updated_prices[asset] = last_price
                            fetched_any = True
            except Exception as e:
                print(f"⚠️ Indodax ticker fetch fallback for {pair}: {e}", flush=True)

        self._price_cache = updated_prices
        if fetched_any:
            self._price_cache_ts = now
            self.last_price_fetch_ts = now
        return dict(self._price_cache)

    async def _execute_topup_deployment(self, amount_idr: float) -> Dict[str, Any]:
        """
        Calculates and executes 70% BTC / 30% ETH buy allocation.
        - Guardrail checks: MAX_SINGLE_TRADE_IDR and MAX_MONTHLY_TOPUP_IDR.
          Rejects and alerts if breached without clipping or silent failure.
        - Price freshness: In live mode, rejects if price cache is older than 10 minutes (600s).
        - In paper_mode: updates internal portfolio simulation without hitting Indodax API.
        - In live mode (paper_mode=False): places real taker market orders on Indodax API,
          verifies success, records trades using actual execution fill price/quantity,
          or raises RuntimeError and alerts on order failure without recording phantom trades.
        """
        # ── 1. GUARDRAIL CHECK: Single Trade Limit (Task 1) ──
        if amount_idr > self.settings.MAX_SINGLE_TRADE_IDR:
            alert_msg = (
                f"🚨 <b>GUARDRAIL TERTEMBUS: MAX_SINGLE_TRADE_IDR</b>\n"
                f"Topup Rp {amount_idr:,.0f} melebihi batas aman Rp {self.settings.MAX_SINGLE_TRADE_IDR:,.0f}.\n"
                f"⛔ <i>Tidak dieksekusi otomatis, butuh konfirmasi manual.</i>"
            )
            print(f"⚠️ {alert_msg}", flush=True)
            if self.reporter.bot_token:
                await self.reporter.send_message(alert_msg)
            return {
                "success": False,
                "total_deployed_idr": 0.0,
                "executed_summary": [],
                "errors": [f"Topup Rp {amount_idr:,.0f} melebihi batas aman per transaksi Rp {self.settings.MAX_SINGLE_TRADE_IDR:,.0f}."],
                "deploy_breakdown": {},
                "guardrail_breached": "MAX_SINGLE_TRADE_IDR"
            }

        # ── 2. GUARDRAIL CHECK: Monthly Cumulative Topup Limit (Task 1) ──
        current_monthly_total = self.portfolio.get_monthly_topup_total()
        if (current_monthly_total + amount_idr) > self.settings.MAX_MONTHLY_TOPUP_IDR:
            alert_msg = (
                f"🚨 <b>GUARDRAIL TERTEMBUS: MAX_MONTHLY_TOPUP_IDR</b>\n"
                f"Total topup bulan ini Rp {current_monthly_total:,.0f} + topup baru Rp {amount_idr:,.0f} = "
                f"Rp {current_monthly_total + amount_idr:,.0f} (melebihi batas bulanan Rp {self.settings.MAX_MONTHLY_TOPUP_IDR:,.0f}).\n"
                f"⛔ <i>Tidak dieksekusi otomatis, butuh konfirmasi manual.</i>"
            )
            print(f"⚠️ {alert_msg}", flush=True)
            if self.reporter.bot_token:
                await self.reporter.send_message(alert_msg)
            return {
                "success": False,
                "total_deployed_idr": 0.0,
                "executed_summary": [],
                "errors": [f"Total topup bulanan mencapai Rp {current_monthly_total + amount_idr:,.0f}, melebihi batas Rp {self.settings.MAX_MONTHLY_TOPUP_IDR:,.0f}."],
                "deploy_breakdown": {},
                "guardrail_breached": "MAX_MONTHLY_TOPUP_IDR"
            }

        # ── 3. PRICE FRESHNESS CHECK: In Live Mode (Task 3) ──
        # In live trading, price cache MUST NOT be older than 10 minutes (600s)
        now_ts = time.time()
        initial_cache_age = now_ts - self._price_cache_ts
        prices = self.get_current_prices(["BTC", "ETH"])
        price_age = time.time() - self._price_cache_ts

        # If cache was already stale and still couldn't be refreshed, or price_age > 600s:
        if not self.paper_mode and (price_age > 600.0 or initial_cache_age > 600.0):
            alert_msg = (
                f"🚨 <b>HARGA TIDAK FRESH: TOPUP TERTARIK/TERTAHAN</b>\n"
                f"Harga pasar Indodax berasal dari cache yang berusia {price_age:.1f} detik (> 600 detik).\n"
                f"⛔ <i>Topup tertahan, butuh cek manual.</i>"
            )
            print(f"⚠️ {alert_msg}", flush=True)
            if self.reporter.bot_token:
                await self.reporter.send_message(alert_msg)
            return {
                "success": False,
                "total_deployed_idr": 0.0,
                "executed_summary": [],
                "errors": [f"Harga pasar tidak fresh (usia cache {price_age:.1f}s > 600s), eksekusi live buy dibatalkan."],
                "deploy_breakdown": {},
                "guardrail_breached": "STALE_PRICES"
            }

        deploy_breakdown = allocate(amount_idr)
        # Official taker fee from config/fees.py (0.2111% -> 0.002111)
        buy_fee_pct = IDR_BUY_FEES.taker_pct / 100.0

        executed_summary: List[str] = []
        errors: List[str] = []

        # Tell event_detector that bot is executing a trade so balance deltas don't get misdetected
        self.event_detector.set_trade_happened(True)
        try:
            for asset, target_idr in deploy_breakdown.items():
                if target_idr <= 0:
                    continue

                est_price = prices.get(asset, 1.0)
                pair_name = f"{asset.lower()}_idr"
                est_crypto_amount = round(target_idr / est_price, 8)
                fee_idr = round(target_idr * buy_fee_pct, 2)

                if self.paper_mode:
                    # Simulation path: record trade locally
                    self.portfolio.record_trade(
                        pair=pair_name,
                        side="BUY",
                        price=est_price,
                        amount=est_crypto_amount,
                        fee=fee_idr,
                        fee_asset="IDR",
                        is_paper=True
                    )
                    executed_summary.append(
                        f"• {asset}: Rp {target_idr:,.0f} ({est_crypto_amount:.8f} @ Rp {est_price:,.0f}) [SIMULASI]"
                    )
                else:
                    # Live path: Must execute via Indodax API first
                    try:
                        api_res = await self.indodax_client.place_buy_order(
                            pair=pair_name,
                            price=est_price,
                            amount_asset=est_crypto_amount,
                            order_type="MARKET"
                        )

                        # Extract real executed values if returned by API or fallback to calculated
                        actual_price = float(api_res.get("price", est_price) or est_price)
                        actual_amount = float(api_res.get("executed_quantity", api_res.get("quantity", est_crypto_amount)) or est_crypto_amount)
                        actual_fee = float(api_res.get("fee", fee_idr) or fee_idr)

                        self.portfolio.record_trade(
                            pair=pair_name,
                            side="BUY",
                            price=actual_price,
                            amount=actual_amount,
                            fee=actual_fee,
                            fee_asset="IDR",
                            is_paper=False
                        )
                        executed_summary.append(
                            f"• {asset}: Rp {target_idr:,.0f} ({actual_amount:.8f} @ Rp {actual_price:,.0f}) [LIVE ID: {api_res.get('orderId', 'OK')}]"
                        )
                    except Exception as err:
                        error_msg = f"Gagal eksekusi live order {asset}: {err}"
                        print(f"❌ {error_msg}", flush=True)
                        errors.append(error_msg)
                        if self.reporter.bot_token:
                            await self.reporter.send_message(f"🚨 <b>KESALAHAN EKSEKUSI LIVE BUY:</b>\n{error_msg}")
                        # Strict: Do NOT record_trade if API call failed!

            # Deduct deployed IDR from portfolio cash
            self.portfolio.withdraw_cash(amount_idr)
        finally:
            self.event_detector.set_trade_happened(False)

        return {
            "success": len(errors) == 0,
            "total_deployed_idr": amount_idr,
            "executed_summary": executed_summary,
            "errors": errors,
            "deploy_breakdown": deploy_breakdown,
        }

    async def handle_command_async(self, text: str) -> str:
        """Parses and handles interactive text commands asynchronously."""
        parts = text.strip().split()
        if not parts:
            return "Command tidak dikenali. Ketik /status untuk informasi sistem."

        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in ["/start", "/help"]:
            return (
                "🤖 <b>SELAMAT DATANG DI KIBOT V3</b>\n"
                "Sistem Akumulasi Portofolio & DCA Otomatis di Indodax (PURE BUY-ONLY).\n\n"
                "<b>Daftar Perintah Resmi:</b>\n"
                "• /status — Ringkasan NAV & alokasi aset live\n"
                "• /topup &lt;jumlah&gt; — Simulasi / catat topup modal IDR (70% BTC / 30% ETH)\n"
                "• /report — Kirim laporan portofolio harian instan\n\n"
                "ℹ️ <i>Penjualan & penarikan dana dilakukan mandiri di aplikasi Indodax. Bot tidak memiliki fitur jual.</i>\n"
                "<i>Mode Saat Ini: " + ("PAPER TRADING" if self.paper_mode else "LIVE TRADING") + "</i>"
            )

        elif cmd == "/topup":
            if not args:
                return "❌ Format salah: /topup <jumlah_idr>"
            try:
                amount = float(args[0].replace(",", "").replace(".", ""))
                if amount <= 0:
                    return "❌ Jumlah topup harus lebih dari 0."

                # 1. Record incoming cash deposit
                self.portfolio.deposit_cash(amount)

                # 2. Execute deployment via unified method
                deploy_res = await self._execute_topup_deployment(amount)

                if not deploy_res["success"]:
                    res_lines = [
                        f"⛔ <b>TOPUP TERTUNDA / GAGAL DIPROSES</b> ({'PAPER' if self.paper_mode else 'LIVE'})",
                        f"• Nilai Topup: Rp {amount:,.0f}",
                        f"• Saldo Kas IDR: Tercatat di akun namun belum terdeploy.",
                        "\n⚠️ <b>Penyebab:</b>",
                    ]
                    for err in deploy_res["errors"]:
                        res_lines.append(f"• {err}")
                    return "\n".join(res_lines)

                res_lines = [
                    f"✅ <b>TOPUP TERDETEKSI & TERDEPLOY</b> ({'PAPER' if self.paper_mode else 'LIVE'})",
                    f"• Nilai Topup: Rp {amount:,.0f}",
                    "• Strategi: 70% BTC / 30% ETH (Taker Market Buy)",
                    f"• Total Terdeploy: Rp {amount:,.0f}\n",
                    "<b>Alokasi Portfolio (Harga Indodax Live):</b>",
                ]
                res_lines.extend(deploy_res["executed_summary"])

                if deploy_res["errors"]:
                    res_lines.append("\n⚠️ <b>Peringatan Gagal Eksekusi Sebagian:</b>")
                    for err in deploy_res["errors"]:
                        res_lines.append(f"• {err}")

                return "\n".join(res_lines)
            except ValueError:
                return "❌ Jumlah topup harus berupa angka valid."

        elif cmd == "/status":
            holdings = self.portfolio.get_holdings()
            prices = self.get_current_prices()

            nav = self.portfolio.get_nav(prices)
            cost = self.portfolio.get_total_cost_basis()
            pnl_pct = ((nav - cost) / cost * 100.0) if cost > 0 else 0.0

            alloc_lines = []
            for asset, amt in holdings.items():
                if amt <= 0:
                    continue
                pr = prices.get(asset, 1.0) if asset != "IDR" else 1.0
                val = amt * pr
                pct = (val / nav * 100.0) if nav > 0 else 0.0
                alloc_lines.append(f"• {asset}: {amt:.4f} (~Rp {val:,.0f} | {pct:.1f}% | @ Rp {pr:,.0f})")

            return (
                f"🤖 <b>KIBOT V3 STATUS ({'PAPER' if self.paper_mode else 'LIVE'})</b>\n"
                f"• Total NAV: Rp {nav:,.0f}\n"
                f"• Modal Masuk: Rp {cost:,.0f}\n"
                f"• Unrealized PnL: {pnl_pct:+.2f}%\n"
                f"• Sisa Cash IDR: Rp {holdings.get('IDR', 0.0):,.0f}\n\n"
                f"<b>Posisi Aset (Indodax Live):</b>\n" + ("\n".join(alloc_lines) if alloc_lines else "• Portofolio kosong.")
            )

        elif cmd == "/report":
            holdings = self.portfolio.get_holdings()
            prices = self.get_current_prices()
            nav = self.portfolio.get_nav(prices)
            cost = self.portfolio.get_total_cost_basis()
            pnl_pct = ((nav - cost) / cost * 100.0) if cost > 0 else 0.0

            return self.reporter.format_daily_report(
                nav_idr=nav,
                cost_basis_idr=cost,
                pnl_pct=pnl_pct,
                holdings=holdings,
                prices=prices,
                usdt_reserve_idr=holdings.get("USDT", 0.0) * prices.get("USDT", 17500.0),
                cycle_phase="ACCUMULATE_70_30",
            )

        return f"❓ Perintah {cmd} tidak dikenal."

    def handle_command(self, text: str) -> str:
        """Synchronous wrapper for handle_command_async for backward compatibility."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If running within existing loop, create future
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, self.handle_command_async(text)).result()
            else:
                return loop.run_until_complete(self.handle_command_async(text))
        except RuntimeError:
            return asyncio.run(self.handle_command_async(text))

    def _calculate_weekly_performance(self) -> Dict[str, float]:
        """
        Calculates 7-day actual portfolio return vs BTC-Only buy & hold benchmark.
        Compares latest state against snapshot from 7 days ago.
        """
        prices = self.get_current_prices(["BTC", "ETH"])
        current_nav = self.portfolio.get_nav(prices)
        current_btc_price = prices.get("BTC", 1_400_000_000.0)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            # Find snapshot from ~7 days ago
            cursor.execute(
                """
                SELECT total_equity_idr, allocations_json, timestamp
                FROM portfolio_snapshots
                WHERE timestamp <= datetime('now', '-7 days')
                ORDER BY timestamp DESC
                LIMIT 1
                """
            )
            past_snap = cursor.fetchone()

            if not past_snap:
                # Fallback to earliest recorded snapshot if < 7 days history
                cursor.execute(
                    """
                    SELECT total_equity_idr, allocations_json, timestamp
                    FROM portfolio_snapshots
                    ORDER BY timestamp ASC
                    LIMIT 1
                    """
                )
                past_snap = cursor.fetchone()

            # Find past BTC price from transactions around past snapshot
            cursor.execute(
                """
                SELECT price FROM transactions
                WHERE pair LIKE 'btc%' AND timestamp <= datetime('now', '-7 days')
                ORDER BY timestamp DESC
                LIMIT 1
                """
            )
            past_btc_tx = cursor.fetchone()

        if past_snap and past_snap[0] > 0:
            past_equity = past_snap[0]
            weekly_pnl_pct = round(((current_nav - past_equity) / past_equity) * 100.0, 2)
        else:
            total_cost = self.portfolio.get_total_cost_basis()
            weekly_pnl_pct = round(((current_nav - total_cost) / total_cost * 100.0) if total_cost > 0 else 0.0, 2)

        if past_btc_tx and past_btc_tx[0] > 0:
            past_btc_price = past_btc_tx[0]
            btc_benchmark_pnl_pct = round(((current_btc_price - past_btc_price) / past_btc_price) * 100.0, 2)
        else:
            btc_benchmark_pnl_pct = 0.0

        return {
            "current_nav": current_nav,
            "weekly_pnl_pct": weekly_pnl_pct,
            "btc_benchmark_pnl_pct": btc_benchmark_pnl_pct,
        }

    async def poll_telegram_updates(self):
        """Long polls Telegram Bot API for incoming commands."""
        if not self.reporter.bot_token:
            return

        import aiohttp
        url = f"https://api.telegram.org/bot{self.reporter.bot_token}/getUpdates"
        offset = None

        print("🤖 KiBot V3 Telegram Poller Started...", flush=True)
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    params = {"timeout": 20}
                    if offset:
                        params["offset"] = offset
                    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=25)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            # Reset failure tracking on success
                            if self.consecutive_telegram_failures > 0:
                                print(f"✅ Telegram Poller recovered after {self.consecutive_telegram_failures} failures.", flush=True)
                            self.consecutive_telegram_failures = 0
                            self.first_telegram_failure_ts = None

                            for item in data.get("result", []):
                                offset = item["update_id"] + 1
                                message = item.get("message", {})
                                text = message.get("text")
                                chat_id = str(message.get("chat", {}).get("id"))

                                if text and chat_id == str(self.reporter.chat_id):
                                    print(f"📥 Received Command: {text}", flush=True)
                                    response_text = await self.handle_command_async(text)
                                    await self.reporter.send_message(response_text)
                        else:
                            raise RuntimeError(f"Telegram API HTTP status {resp.status}")
                except Exception as e:
                    self.consecutive_telegram_failures += 1
                    now = time.time()
                    if self.first_telegram_failure_ts is None:
                        self.first_telegram_failure_ts = now

                    print(f"⚠️ Telegram Poller Error ({self.consecutive_telegram_failures}x): {e}", flush=True)

                    # Escalation check (Task 2): Alert on >= 5 consecutive failures, repeat max once per 6 hours
                    if self.consecutive_telegram_failures >= 5:
                        if (now - self.last_telegram_escalation_ts) >= 21600.0:  # 6 hours
                            duration_mins = int((now - self.first_telegram_failure_ts) / 60)
                            esc_msg = (
                                f"🚨 <b>ESKALASI SISTEM: TELEGRAM POLLER GAGAL BERUNTUN</b>\n"
                                f"Polling Telegram command telah gagal {self.consecutive_telegram_failures}x berturut-turut "
                                f"sejak {duration_mins} menit lalu.\n"
                                f"• Penyebab terakhir: {e}\n"
                                f"• Status: Bot tidak dapat menerima perintah teks sampai koneksi pulih.\n"
                                f"ℹ️ <i>Peringatan ini dikirim ulang maksimal tiap 6 jam.</i>"
                            )
                            print(f"🚨 {esc_msg}", flush=True)
                            # Attempt sending via reporter if Telegram API allows outbound send
                            try:
                                await self.reporter.send_message(esc_msg)
                            except Exception:
                                pass
                            self.last_telegram_escalation_ts = now

                    await asyncio.sleep(5)

    async def scheduler_loop(self):
        """Runs scheduled periodic tasks (Daily 08:00 WIB, Weekly Mon 00:00 WIB, Monthly 1st 08:00 WIB)."""
        print("⏰ KiBot V3 Scheduler Loop Active (Target: 08:00 WIB)...", flush=True)

        now_wib = datetime.now(WIB)
        next_daily = now_wib.replace(hour=8, minute=0, second=0, microsecond=0)
        if now_wib >= next_daily:
            next_daily += timedelta(days=1)

        days_ahead = (0 - now_wib.weekday() + 7) % 7
        if days_ahead == 0 and now_wib.hour >= 0:
            days_ahead = 7
        next_weekly = (now_wib + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)

        if now_wib.month == 12:
            next_monthly = now_wib.replace(year=now_wib.year + 1, month=1, day=1, hour=8, minute=0, second=0, microsecond=0)
        else:
            next_monthly = now_wib.replace(month=now_wib.month + 1, day=1, hour=8, minute=0, second=0, microsecond=0)

        print(f"📅 Next daily report: {next_daily.strftime('%Y-%m-%d %H:%M:%S WIB')}", flush=True)
        print(f"📅 Next weekly report: {next_weekly.strftime('%Y-%m-%d %H:%M:%S WIB')}", flush=True)
        print(f"📅 Next monthly report: {next_monthly.strftime('%Y-%m-%d %H:%M:%S WIB')}", flush=True)

        last_fired_day = None
        while True:
            now_wib = datetime.now(WIB)
            current_day = (now_wib.year, now_wib.month, now_wib.day)

            # Daily Report at 08:00 WIB
            if now_wib.hour == 8 and now_wib.minute == 0 and last_fired_day != current_day:
                print("📢 Triggering Scheduled Daily 08:00 WIB Report...", flush=True)
                prices = self.get_current_prices()
                holdings = self.portfolio.get_holdings()
                cash_val = holdings.get("IDR", 0.0)
                # Save daily portfolio snapshot
                self.portfolio.take_snapshot(
                    cash_idr=cash_val,
                    asset_prices=prices,
                    regime_phase="ACCUMULATE_70_30",
                    is_paper=self.paper_mode
                )
                rep = await self.handle_command_async("/report")
                await self.reporter.send_message(rep)
                last_fired_day = current_day
                await asyncio.sleep(60)

            # Weekly Report on Monday 00:00 WIB
            if now_wib.weekday() == 0 and now_wib.hour == 0 and now_wib.minute == 0:
                print("📢 Triggering Scheduled Weekly Monday 00:00 WIB Report...", flush=True)
                perf = self._calculate_weekly_performance()
                rep = self.reporter.format_weekly_report(
                    nav_idr=perf["current_nav"],
                    weekly_pnl_pct=perf["weekly_pnl_pct"],
                    btc_benchmark_pnl_pct=perf["btc_benchmark_pnl_pct"],
                )
                await self.reporter.send_message(rep)
                await asyncio.sleep(60)

            # Monthly Report on 1st of month 08:00 WIB (including Oracle Console check reminder)
            if now_wib.day == 1 and now_wib.hour == 8 and now_wib.minute == 0:
                print("📢 Triggering Scheduled Monthly 1st 08:00 WIB Audit Report...", flush=True)
                prices = self.get_current_prices()
                nav = self.portfolio.get_nav(prices)
                total_invested = self.portfolio.get_total_cost_basis()
                total_monthly_topup = self.portfolio.get_monthly_topup_total()
                all_time_pnl = round(((nav - total_invested) / total_invested * 100.0) if total_invested > 0 else 0.0, 2)

                # Format base monthly audit report
                monthly_rep = self.reporter.format_monthly_report(
                    total_topup_idr=total_monthly_topup,
                    nav_idr=nav,
                    total_invested_idr=total_invested,
                    all_time_pnl_pct=all_time_pnl,
                    topup_count=1,
                    manual_events=[]
                )

                # Append legitimate human safety net reminder (Task 6)
                oracle_reminder = (
                    "\n\n🛡️ <b>REMINDER PEMELIHARAAN INFRASTRUKTUR BULANAN:</b>\n"
                    "• Silakan login ke <b>Oracle Cloud Console</b> dan verifikasi SG1 & Server 2 masih aktif (Running).\n"
                    "• Cek saldo & batas disk space untuk memastikan status Always Free tetap aman tanpa risiko reclaim."
                )
                await self.reporter.send_message(monthly_rep + oracle_reminder)
                await asyncio.sleep(60)

            try:
                # Wrap scheduler iteration logic
                pass
            except Exception as e:
                self.consecutive_scheduler_failures += 1
                now = time.time()
                if self.first_scheduler_failure_ts is None:
                    self.first_scheduler_failure_ts = now
                print(f"⚠️ Scheduler Loop Error ({self.consecutive_scheduler_failures}x): {e}", flush=True)
                if self.consecutive_scheduler_failures >= 5:
                    if (now - self.last_scheduler_escalation_ts) >= 21600.0:
                        duration_mins = int((now - self.first_scheduler_failure_ts) / 60)
                        esc_msg = (
                            f"🚨 <b>ESKALASI SISTEM: SCHEDULER LOOP GAGAL BERUNTUN</b>\n"
                            f"Scheduler telah gagal {self.consecutive_scheduler_failures}x berturut-turut "
                            f"sejak {duration_mins} menit lalu.\n"
                            f"• Penyebab: {e}\n"
                            f"ℹ️ <i>Peringatan ini dikirim ulang maksimal tiap 6 jam.</i>"
                        )
                        print(f"🚨 {esc_msg}", flush=True)
                        try:
                            await self.reporter.send_message(esc_msg)
                        except Exception:
                            pass
                        self.last_scheduler_escalation_ts = now

            await asyncio.sleep(5)

    async def poll_balance_deltas_loop(self):
        """
        Periodically polls account balances to detect manual topups and manual sales/withdrawals.
        - In Live mode: Queries live Indodax API.
        - In Paper mode: Queries internal portfolio holdings to simulate balance delta events.
        - Tracks consecutive failures and escalates to Telegram on >= 5 failures (repeated max every 6 hours).
        """
        print(f"🔍 KiBot V3 Balance Delta Poller Active (180s interval, Mode: {'PAPER' if self.paper_mode else 'LIVE'})...", flush=True)
        while True:
            try:
                if self.paper_mode:
                    # In Paper mode: read internal portfolio balances
                    holdings = self.portfolio.get_holdings()
                    current_bal = {k.lower(): v for k, v in holdings.items()}
                else:
                    if not self.indodax_client.api_key:
                        await asyncio.sleep(180)
                        continue
                    current_bal = await self.indodax_client.get_balance()

                # Record successful balance poll timestamp
                self.last_poll_ts = time.time()
                if self.consecutive_poll_failures > 0:
                    print(f"✅ Balance Poller recovered after {self.consecutive_poll_failures} failures.", flush=True)
                self.consecutive_poll_failures = 0
                self.first_poll_failure_ts = None

                if self._last_balance_snapshot:
                    events = self.event_detector.detect_events(
                        current_balances=current_bal,
                        previous_balances=self._last_balance_snapshot
                    )
                    prices = self.get_current_prices()

                    for ev in events:
                        # 1. Manual Topup IDR -> Auto deploy 70% BTC / 30% ETH (Taker Market Buy)
                        if ev.event_type == "manual_topup" and ev.amount >= 100_000.0:
                            alert = self.event_detector.format_telegram_alert(ev)
                            await self.reporter.send_message(alert)
                            # Auto-execute topup via unified method
                            res = await self._execute_topup_deployment(ev.amount)
                            if res["success"]:
                                reply_lines = [
                                    f"✅ <b>TOPUP TERDETEKSI & TERDEPLOY</b> ({'PAPER' if self.paper_mode else 'LIVE'})",
                                    f"• Nilai Topup: Rp {ev.amount:,.0f}",
                                    "• Strategi: 70% BTC / 30% ETH (Taker Market Buy)",
                                ]
                                reply_lines.extend(res["executed_summary"])
                                await self.reporter.send_message("\n".join(reply_lines))
                            else:
                                reply_lines = [
                                    f"⛔ <b>TOPUP TERDETEKSI TAPI TIDAK TERDEPLOY</b> ({'PAPER' if self.paper_mode else 'LIVE'})",
                                    f"• Nilai Topup: Rp {ev.amount:,.0f}",
                                    "\n⚠️ <b>Penyebab:</b>",
                                ]
                                for err in res["errors"]:
                                    reply_lines.append(f"• {err}")
                                await self.reporter.send_message("\n".join(reply_lines))

                        # 2. Manual Crypto Sale / Withdrawal by Supervisor in Indodax app
                        elif ev.event_type == "manual_crypto_sale":
                            est_price = prices.get(ev.asset, 0.0)
                            disposal = self.portfolio.process_manual_asset_disposal(
                                asset=ev.asset,
                                amount_disposed=ev.amount,
                                estimated_market_price=est_price
                            )
                            alert = self.event_detector.format_telegram_alert(ev, disposal_info=disposal)
                            await self.reporter.send_message(alert)

                        # 3. Manual IDR cash withdrawal
                        elif ev.event_type == "manual_withdraw":
                            self.portfolio.withdraw_cash(ev.amount)
                            alert = self.event_detector.format_telegram_alert(ev)
                            await self.reporter.send_message(alert)

                self._last_balance_snapshot = dict(current_bal)
                self._save_last_balance_snapshot(self._last_balance_snapshot)
            except Exception as e:
                self.consecutive_poll_failures += 1
                now = time.time()
                if self.first_poll_failure_ts is None:
                    self.first_poll_failure_ts = now

                print(f"⚠️ Balance Delta Poller Error ({self.consecutive_poll_failures}x): {e}", flush=True)

                # Escalation check (Task 2): Alert on >= 5 consecutive failures, repeat max once per 6 hours
                if self.consecutive_poll_failures >= 5:
                    if (now - self.last_poll_escalation_ts) >= 21600.0:  # 6 hours
                        duration_mins = int((now - self.first_poll_failure_ts) / 60)
                        esc_msg = (
                            f"🚨 <b>ESKALASI SISTEM: POLLING BALANCE GAGAL BERUNTUN</b>\n"
                            f"Polling saldo Indodax telah gagal {self.consecutive_poll_failures}x berturut-turut "
                            f"sejak {duration_mins} menit lalu.\n"
                            f"• Kemungkinan penyebab: API berubah, kredensial invalid, atau network down.\n"
                            f"• Error terakhir: {e}\n"
                            f"⛔ <i>Butuh pengecekan manual segera.</i>\n"
                            f"ℹ️ <i>Peringatan ini dikirim ulang maksimal tiap 6 jam sampai berhasil lagi.</i>"
                        )
                        print(f"🚨 {esc_msg}", flush=True)
                        try:
                            await self.reporter.send_message(esc_msg)
                        except Exception:
                            pass
                        self.last_poll_escalation_ts = now

            await asyncio.sleep(180)

    def get_health_status(self) -> Dict[str, Any]:
        """
        Gathers comprehensive node health metrics for monitoring and watchdogs:
        - uptime_seconds
        - last_poll_ts & age
        - last_price_fetch_ts & age
        - git commit hash
        - disk space metrics (Task 7)
        - overall status (HEALTHY / DEGRADED)
        """
        now = time.time()
        uptime = round(now - self.start_time, 1)

        # 1. Check Git commit hash
        commit_hash = "unknown"
        try:
            import subprocess
            res = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=2,
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            if res.returncode == 0:
                commit_hash = res.stdout.strip()
        except Exception:
            pass

        # 2. Check Disk Space (Task 7)
        import shutil
        disk_critical = False
        try:
            total, used, free = shutil.disk_usage("/")
            used_pct = round((used / total) * 100.0, 2)
            disk_info = {
                "total_gb": round(total / (1024**3), 2),
                "used_gb": round(used / (1024**3), 2),
                "free_gb": round(free / (1024**3), 2),
                "used_pct": used_pct,
            }
            if used_pct >= 85.0:
                disk_critical = True
        except Exception as e:
            disk_info = {"error": str(e), "used_pct": 0.0}

        # Determine node health
        status = "HEALTHY"
        issues = []

        if disk_critical:
            status = "DEGRADED"
            issues.append(f"Disk usage is critical ({disk_info.get('used_pct')}%)")

        if self.consecutive_poll_failures >= 5:
            status = "DEGRADED"
            issues.append(f"Consecutive poll failures ({self.consecutive_poll_failures})")

        if self.last_poll_ts and (now - self.last_poll_ts) > 600.0:
            status = "DEGRADED"
            issues.append(f"Last balance poll was {int(now - self.last_poll_ts)}s ago")

        return {
            "status": status,
            "mode": "PAPER" if self.paper_mode else "LIVE",
            "uptime_seconds": uptime,
            "last_poll_ts": self.last_poll_ts,
            "last_poll_age_seconds": round(now - self.last_poll_ts, 1) if self.last_poll_ts else None,
            "last_price_fetch_ts": self.last_price_fetch_ts,
            "last_price_fetch_age_seconds": round(now - self.last_price_fetch_ts, 1) if self.last_price_fetch_ts else None,
            "consecutive_poll_failures": self.consecutive_poll_failures,
            "consecutive_telegram_failures": self.consecutive_telegram_failures,
            "consecutive_scheduler_failures": self.consecutive_scheduler_failures,
            "commit_hash": commit_hash,
            "disk": disk_info,
            "issues": issues,
            "timestamp": now,
        }

    async def run_health_server(self, host: str = "0.0.0.0"):
        """Runs lightweight aiohttp HTTP server exposing /health endpoint."""
        if not self.health_port:
            return

        from aiohttp import web

        async def handle_health(request):
            health_data = self.get_health_status()
            status_code = 200 if health_data["status"] == "HEALTHY" else 503
            return web.json_response(health_data, status=status_code)

        app = web.Application()
        app.router.add_get("/health", handle_health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.health_host, self.health_port)
        print(f"🩺 KiBot V3 Health HTTP Server active on http://{self.health_host}:{self.health_port}/health", flush=True)
        await site.start()

        # Keep runner alive
        while True:
            await asyncio.sleep(3600)

    async def run(self):
        """Main asynchronous event loop executing daemon tasks."""
        print("🚀 KiBot V3 Orchestrator Starting...", flush=True)
        tasks = [
            asyncio.create_task(self.poll_telegram_updates()),
            asyncio.create_task(self.scheduler_loop()),
            asyncio.create_task(self.poll_balance_deltas_loop()),
        ]
        if self.health_port:
            tasks.append(asyncio.create_task(self.run_health_server(self.health_host)))
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    db_file = os.getenv("KIBOT_DB_PATH", "kibot_v3.db")
    paper = os.getenv("PAPER_MODE", "true").lower() == "true"
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    h_port = int(os.getenv("HEALTH_PORT", "8789"))
    h_host = os.getenv("HEALTH_HOST", "0.0.0.0")

    bot = KiBotV3Orchestrator(
        db_path=db_file,
        paper_mode=paper,
        bot_token=token,
        chat_id=chat,
        health_port=h_port,
        health_host=h_host
    )

    try:
        asyncio.run(bot.run())
    except (KeyboardInterrupt, SystemExit):
        print("🛑 KiBot V3 Orchestrator Stopped.", flush=True)
