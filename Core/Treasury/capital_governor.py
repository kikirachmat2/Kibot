import logging
import json
import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from Core.Support.ki_config import WIB, KiConfig
from Core.Treasury.venue_ledger import VenueLedger
from Core.Treasury.phantom_treasury import PhantomTreasury
from Core.Treasury.allocation_policy import AllocationPolicy

logger = logging.getLogger("CapitalGovernor")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
GOVERNOR_FILE = STATE_DIR / "capital_governor.json"

def _today_wib() -> str:
    """Business day boundary follows WIB."""
    return str(datetime.now(WIB).date())

class CapitalGovernor:
    """
    Sovereign Capital Governor
    =========================
    The central coordinator of KiBot's capital distribution, target allocations,
    and the global 1.5% daily drawdown cap.
    """
    def __init__(self, indodax_gateway=None, phantom_router=None):
        self.indodax = indodax_gateway
        self.phantom_router = phantom_router
        
        # Initialize internal modules
        self.ledger = VenueLedger()
        self.phantom_treasury = PhantomTreasury(phantom_router)
        self.policy = AllocationPolicy()
        
        # Core metrics
        self.start_total_equity_idr = 0.0
        self.max_daily_loss_idr = 0.0
        self.current_total_equity_idr = 0.0
        self.daily_pnl_idr = 0.0
        self.daily_pnl_pct = 0.0
        self.trading_pnl_idr = 0.0
        self.trading_pnl_pct = 0.0
        self.start_indodax_equity_idr = 0.0
        self.start_phantom_equity_idr = 0.0
        self.indodax_daily_pnl_idr = 0.0
        self.indodax_daily_pnl_pct = 0.0
        self.phantom_daily_pnl_idr = 0.0
        self.phantom_daily_pnl_pct = 0.0
        self.external_deposits_today = 0.0
        self.external_withdrawals_today = 0.0
        self.reset_deposits_offset = 0.0
        self.reset_withdrawals_offset = 0.0
        self.status = "UNRECONCILED"
        self.last_reset_date = _today_wib()
        
        self._load_governor_state()

    def _load_governor_state(self):
        self.status = "UNRECONCILED"
        if GOVERNOR_FILE.exists():
            try:
                with open(GOVERNOR_FILE, "r") as f:
                    data = json.load(f)
                    today = _today_wib()
                    if data.get("date") == today:
                        self.start_total_equity_idr = float(data.get("start_total_equity_idr", 0.0))
                        self.max_daily_loss_idr = float(data.get("max_daily_loss_idr", 0.0))
                        self.last_reset_date = today
                        self.status = data.get("status", "UNRECONCILED")
                        self.daily_pnl_idr = float(data.get("daily_pnl_idr", 0.0))
                        self.daily_pnl_pct = float(data.get("daily_pnl_pct", 0.0))
                        self.trading_pnl_idr = float(data.get("trading_pnl_idr", self.daily_pnl_idr))
                        self.trading_pnl_pct = float(data.get("trading_pnl_pct", self.daily_pnl_pct))
                        self.start_indodax_equity_idr = float(data.get("start_indodax_equity_idr", 0.0))
                        self.start_phantom_equity_idr = float(data.get("start_phantom_equity_idr", 0.0))
                        self.indodax_daily_pnl_idr = float(data.get("indodax_daily_pnl_idr", 0.0))
                        self.indodax_daily_pnl_pct = float(data.get("indodax_daily_pnl_pct", 0.0))
                        self.phantom_daily_pnl_idr = float(data.get("phantom_daily_pnl_idr", 0.0))
                        self.phantom_daily_pnl_pct = float(data.get("phantom_daily_pnl_pct", 0.0))
                        self.external_deposits_today = float(data.get("external_deposits_today", 0.0))
                        self.external_withdrawals_today = float(data.get("external_withdrawals_today", 0.0))
                        self.reset_deposits_offset = float(data.get("reset_deposits_offset", 0.0))
                        self.reset_withdrawals_offset = float(data.get("reset_withdrawals_offset", 0.0))
                    else:
                        self.last_reset_date = today
                        self.start_total_equity_idr = 0.0
                        self.max_daily_loss_idr = 0.0
                        self.daily_pnl_idr = 0.0
                        self.daily_pnl_pct = 0.0
                        self.trading_pnl_idr = 0.0
                        self.trading_pnl_pct = 0.0
                        self.start_indodax_equity_idr = 0.0
                        self.start_phantom_equity_idr = 0.0
                        self.indodax_daily_pnl_idr = 0.0
                        self.indodax_daily_pnl_pct = 0.0
                        self.phantom_daily_pnl_idr = 0.0
                        self.phantom_daily_pnl_pct = 0.0
                        self.external_deposits_today = 0.0
                        self.external_withdrawals_today = 0.0
                        self.reset_deposits_offset = 0.0
                        self.reset_withdrawals_offset = 0.0
            except Exception as e:
                logger.error(f"❌ Failed to load Capital Governor state: {e}")
        else:
            self.last_reset_date = _today_wib()

    def save(self):
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            global_hard_stop = bool(self.max_daily_loss_idr > 0.0 and self.daily_pnl_idr <= -self.max_daily_loss_idr)
            status = "BLOCKED_WITH_REASON" if global_hard_stop else self.status
            allow_new_orders = bool(getattr(self, "allow_new_orders", False)) and not global_hard_stop
            allow_reason = str(getattr(self, "allow_new_orders_reason", ""))
            if global_hard_stop and not allow_reason:
                allow_reason = (
                    f"global_daily_loss_cap_breached ({self.daily_pnl_idr:.2f} <= -{self.max_daily_loss_idr:.2f})"
                )
            with open(GOVERNOR_FILE, "w") as f:
                json.dump({
                    "date": self.last_reset_date,
                    "start_total_equity_idr": self.start_total_equity_idr,
                    "max_daily_loss_pct": KiConfig.MAX_DAILY_LOSS_PERCENT,
                    "max_daily_loss_idr": self.max_daily_loss_idr,
                    "current_total_equity_idr": self.current_total_equity_idr,
                    "daily_pnl_idr": self.daily_pnl_idr,
                    "daily_pnl_pct": self.daily_pnl_pct,
                    "trading_pnl_idr": self.trading_pnl_idr,
                    "trading_pnl_pct": self.trading_pnl_pct,
                    "start_indodax_equity_idr": self.start_indodax_equity_idr,
                    "start_phantom_equity_idr": self.start_phantom_equity_idr,
                    "indodax_daily_pnl_idr": self.indodax_daily_pnl_idr,
                    "indodax_daily_pnl_pct": self.indodax_daily_pnl_pct,
                    "phantom_daily_pnl_idr": self.phantom_daily_pnl_idr,
                    "phantom_daily_pnl_pct": self.phantom_daily_pnl_pct,
                    "external_deposits_today": self.external_deposits_today,
                    "external_withdrawals_today": self.external_withdrawals_today,
                    "reset_deposits_offset": self.reset_deposits_offset,
                    "reset_withdrawals_offset": self.reset_withdrawals_offset,
                    "status": status
                    ,
                    "global_hard_stop": global_hard_stop,
                    "allow_new_orders": allow_new_orders,
                    "allow_new_orders_reason": allow_reason,
                    "venues": getattr(self, "venue_states", {}),
                    "targets": getattr(self, "targets_snapshot", {}),
                    "phantom_details": getattr(self, "phantom_details_snapshot", {}),
                }, f, indent=4)
        except Exception as e:
            logger.error(f"❌ Failed to save Capital Governor state: {e}")

    def _read_daily_transfers(self, date_str: str) -> tuple[float, float]:
        """Read state/treasury_transfers.jsonl and sum external deposits and withdrawals for the given date."""
        transfers_file = STATE_DIR / "treasury_transfers.jsonl"
        deposits = 0.0
        withdrawals = 0.0
        if not transfers_file.exists():
            return 0.0, 0.0
        try:
            with open(transfers_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        tx = json.loads(line)
                        if tx.get("date") == date_str:
                            txtype = tx.get("type", "").strip().lower()
                            amount = float(tx.get("amount_idr", 0.0))
                            if txtype == "deposit":
                                deposits += amount
                            elif txtype == "withdrawal":
                                withdrawals += amount
                    except Exception as e:
                        logger.error(f"Error parsing transfer line: {e}")
        except Exception as e:
            logger.error(f"Error reading treasury_transfers.jsonl: {e}")
        return deposits, withdrawals

    def _read_in_flight_transfers(self, date_str: str, phantom_equity_idr: float) -> float:
        """
        Read state/treasury_transfers.jsonl and calculate the total in-flight internal transfer amount
        destined for Phantom that is not yet reflected in its balance.
        """
        transfers_file = STATE_DIR / "treasury_transfers.jsonl"
        in_flight = 0.0
        if not transfers_file.exists():
            return 0.0
        try:
            with open(transfers_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        tx = json.loads(line)
                        if tx.get("date") == date_str:
                            txtype = tx.get("type", "").strip().lower()
                            if txtype == "internal":
                                to_venue = tx.get("to_venue", "").strip().lower()
                                amount = float(tx.get("amount_idr", 0.0))
                                if to_venue == "phantom":
                                    # If the on-chain phantom balance is less than this transfer amount,
                                    # the difference is considered in-flight (in-transit).
                                    if phantom_equity_idr < amount:
                                        in_flight += (amount - phantom_equity_idr)
                    except Exception as e:
                        logger.error(f"Error parsing transfer line: {e}")
        except Exception as e:
            logger.error(f"Error reading treasury_transfers.jsonl: {e}")
        return in_flight

    async def _read_indodax_coin_holdings_from_active_trades(self) -> float:
        """
        Fallback for equity reconciliation when the exchange balance endpoint
        does not expose held coins consistently in the governor process.
        Uses open Indodax positions + live tickers to estimate mark-to-market.
        """
        if os.getenv("KIBOT_GOVERNOR_ACTIVE_TRADES_FALLBACK", "0").strip().lower() not in {"1", "true", "yes", "on"}:
            return 0.0
        active_trades_file = STATE_DIR / "active_trades.json"
        if not active_trades_file.exists():
            return 0.0
        try:
            with open(active_trades_file, "r") as f:
                active_trades = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load active_trades.json for governor fallback: {e}")
            return 0.0

        if not isinstance(active_trades, dict):
            return 0.0

        holdings_value = 0.0
        try:
            for symbol, trade in active_trades.items():
                if not isinstance(trade, dict):
                    continue
                pair = str(symbol or "").lower().replace("/", "_")
                if "_" not in pair:
                    pair = f"{pair}_idr"
                coin = pair.split("_", 1)[0]
                amount = float(trade.get("amount", 0.0) or 0.0)
                if amount <= 0:
                    continue
                try:
                    ticker = await asyncio.wait_for(self.indodax.get_ticker(pair), timeout=5)
                    if not isinstance(ticker, dict):
                        continue
                    price = float(ticker.get("last", 0.0) or 0.0)
                except Exception:
                    price = float(trade.get("price", 0.0) or 0.0)
                if price > 0:
                    holdings_value += amount * price
        except Exception as e:
            logger.error(f"Failed to compute active trade holdings fallback: {e}")
            return 0.0
        return holdings_value


    async def check_daily_reset(self, total_equity_idr: float):
        """Reset starting total equity anchor if a new WIB day has begun."""
        today = _today_wib()
        if self.last_reset_date != today or self.start_total_equity_idr <= 0.0:
            self.last_reset_date = today
            self.start_total_equity_idr = total_equity_idr
            self.max_daily_loss_idr = total_equity_idr * (KiConfig.MAX_DAILY_LOSS_PERCENT / 100.0)
            self.reset_deposits_offset = 0.0
            self.reset_withdrawals_offset = 0.0
            logger.info(f"⚓ Daily Total Equity Anchor Reset: Rp{self.start_total_equity_idr:,.2f} (Cap: Rp{self.max_daily_loss_idr:,.2f})")

    def manual_pnl_reset(self):
        """
        Manually reset the daily PnL anchor to the current consolidated equity.
        Maintains an audit trail by logging and updating the governor state file,
        but does not delete trade or transfer history.
        """
        logger.info(f"🔄 Manual daily PnL anchor reset initiated. Current total equity: Rp{self.current_total_equity_idr:,.2f}")
        
        # Read the raw daily transfers so far to establish the offset
        raw_deposits, raw_withdrawals = self._read_daily_transfers(self.last_reset_date)
        
        self.start_total_equity_idr = self.current_total_equity_idr
        self.max_daily_loss_idr = self.current_total_equity_idr * (KiConfig.MAX_DAILY_LOSS_PERCENT / 100.0)
        self.start_indodax_equity_idr = 0.0
        self.start_phantom_equity_idr = 0.0
        self.reset_deposits_offset = raw_deposits
        self.reset_withdrawals_offset = raw_withdrawals
        self.daily_pnl_idr = 0.0
        self.daily_pnl_pct = 0.0
        self.indodax_daily_pnl_idr = 0.0
        self.indodax_daily_pnl_pct = 0.0
        self.phantom_daily_pnl_idr = 0.0
        self.phantom_daily_pnl_pct = 0.0
        self.external_deposits_today = 0.0
        self.external_withdrawals_today = 0.0
        self.save()
        logger.info(f"⚓ PnL Anchor reset to current reconciled equity. Starting Equity: Rp{self.start_total_equity_idr:,.2f}. Offsets registered: Dep Rp{self.reset_deposits_offset:,.2f}, Wd Rp{self.reset_withdrawals_offset:,.2f}")

    async def reconcile_governor(self) -> Dict[str, Any]:
        """
        Orchestrate wallet balances, update the Venue Ledger,
        apply target allocation policies, and enforce global risk parameters.
        """
        self.status = "UNRECONCILED"
        try:
            # 1. Reconcile Phantom Web3 balances
            await self.phantom_treasury.reconcile_balances()
            phantom_summary = self.phantom_treasury.get_summary()
            phantom_equity_idr = phantom_summary.get("total_value_idr", 0.0)
            
            # 2. Reconcile Indodax balance
            indodax_real_balance = 0.0
            indodax_coin_holdings_idr = 0.0
            if self.indodax:
                try:
                    # Query real balance with 5 second timeout
                    indo_info = await asyncio.wait_for(self.indodax.get_info(), timeout=5)
                    if indo_info.get("success") == 1:
                        balances = indo_info.get("return", {}).get("balance", {})
                        indodax_real_balance = float(balances.get("idr", 0.0) or 0.0)
                        held_coins = []
                        for coin, amount in balances.items():
                            if coin == "idr":
                                continue
                            try:
                                amt = float(amount or 0.0)
                            except Exception:
                                continue
                            if amt > 1e-6:
                                held_coins.append((coin, amt))
                        if held_coins:
                            coin_tasks = []
                            for coin, amt in held_coins:
                                coin_tasks.append(self.indodax.get_ticker(f"{coin}_idr"))
                            try:
                                tickers = await asyncio.gather(*coin_tasks, return_exceptions=True)
                                for (coin, amt), ticker in zip(held_coins, tickers):
                                    if isinstance(ticker, Exception):
                                        continue
                                    try:
                                        price = float(ticker.get("last", 0.0) or 0.0)
                                    except Exception:
                                        price = 0.0
                                    if price > 0:
                                        indodax_coin_holdings_idr += amt * price
                            except Exception as e:
                                logger.error(f"❌ Failed to query Indodax coin holdings: {e}")
                    if indodax_coin_holdings_idr <= 0.0:
                        indodax_coin_holdings_idr = await self._read_indodax_coin_holdings_from_active_trades()
                except Exception as e:
                    logger.error(f"❌ Failed to query Indodax balance: {e}")
                    
            # Shadow reserve is only used when live trading is disabled.
            indodax_shadow_balance = 1000000.0
            shadow_ledger = self.ledger.get_venue("indodax_shadow")
            if shadow_ledger:
                indodax_shadow_balance = shadow_ledger.get("equity_idr", 1000000.0)

            # 3. Calculate Total Consolidated Equity
            # Controlled-live mode takes actual Indodax cash + mark-to-market coin holdings,
            # otherwise shadow reserve.
            primary_indodax_balance = (
                (indodax_real_balance + indodax_coin_holdings_idr)
                if KiConfig.LIVE_TRADING_ENABLED
                else indodax_shadow_balance
            )
            phantom_reconciliation = phantom_summary.get("reconciliation", {}) if isinstance(phantom_summary, dict) else {}
            phantom_ready = (
                phantom_summary.get("status") in {"OK", "SCOUTING"}
                and bool(phantom_reconciliation.get("matches_user_wallet"))
            )
            
            # Read in-flight internal transfers destined for Phantom
            in_flight_idr = self._read_in_flight_transfers(self.last_reset_date, phantom_equity_idr)

            # Venue-specific anchors keep one venue's drawdown from blocking the others.
            if self.start_indodax_equity_idr <= 0.0:
                self.start_indodax_equity_idr = float(primary_indodax_balance or 0.0)
            if self.start_phantom_equity_idr <= 0.0:
                self.start_phantom_equity_idr = float(phantom_equity_idr or 0.0)
            if self.start_indodax_equity_idr <= 0.0:
                self.start_indodax_equity_idr = float(primary_indodax_balance or 0.0)
            if self.start_phantom_equity_idr <= 0.0:
                self.start_phantom_equity_idr = float(phantom_equity_idr or 0.0)

            indodax_daily_loss_cap_idr = self.start_indodax_equity_idr * (KiConfig.MAX_DAILY_LOSS_PERCENT / 100.0)
            phantom_daily_loss_cap_idr = self.start_phantom_equity_idr * (KiConfig.MAX_DAILY_LOSS_PERCENT / 100.0)
            self.indodax_daily_pnl_idr = primary_indodax_balance - self.start_indodax_equity_idr
            self.phantom_daily_pnl_idr = phantom_equity_idr - self.start_phantom_equity_idr
            self.indodax_daily_pnl_pct = (self.indodax_daily_pnl_idr / max(self.start_indodax_equity_idr, 1.0)) * 100.0
            self.phantom_daily_pnl_pct = (self.phantom_daily_pnl_idr / max(self.start_phantom_equity_idr, 1.0)) * 100.0
            
            # Total Consolidated Equity = Primary Indodax Balance + Phantom Balance + In-flight internal transfers
            self.current_total_equity_idr = primary_indodax_balance + phantom_equity_idr + in_flight_idr
            
            # Check and initialize today's start anchor if needed
            await self.check_daily_reset(self.current_total_equity_idr)
            
            # Read daily transfers to adjust starting equity
            deposits, withdrawals = self._read_daily_transfers(self.last_reset_date)
            adjusted_deposits = deposits - self.reset_deposits_offset
            adjusted_withdrawals = withdrawals - self.reset_withdrawals_offset
            
            self.external_deposits_today = adjusted_deposits
            self.external_withdrawals_today = adjusted_withdrawals
            
            # Compute daily consolidated PnL (adjusted for capital flows and offset)
            self.daily_pnl_idr = self.current_total_equity_idr - self.start_total_equity_idr - adjusted_deposits + adjusted_withdrawals
            self.trading_pnl_idr = self.current_total_equity_idr - self.start_total_equity_idr
            
            # Compute PnL percentage
            if self.start_total_equity_idr > 0.0:
                self.daily_pnl_pct = (self.daily_pnl_idr / self.start_total_equity_idr) * 100.0
                self.trading_pnl_pct = (self.trading_pnl_idr / self.start_total_equity_idr) * 100.0
            else:
                self.daily_pnl_pct = 0.0
                self.trading_pnl_pct = 0.0
                
            indodax_ready = (indodax_real_balance + indodax_coin_holdings_idr) > 0
            self.status = "RECONCILED" if (phantom_ready or indodax_ready) else "DEGRADED"
            if not phantom_ready:
                logger.warning("⚠️ Phantom treasury not yet reconciled; live Phantom routes remain venue-scoped.")
            
            # 4. Compute target allocation split
            targets = self.policy.compute_targets(phantom_equity_idr)
            
            # 5. Sync to Venue Ledger
            self.ledger.update_venue("indodax_real", equity_idr=indodax_real_balance + indodax_coin_holdings_idr)
            self.ledger.update_venue("indodax_shadow", equity_idr=indodax_shadow_balance)
            self.ledger.update_venue("phantom", equity_idr=phantom_equity_idr)
            self.ledger.update_venue("cash_wait", equity_idr=self.current_total_equity_idr * targets.get("reserve", 0.20))

            global_hard_stop = bool(
                self.max_daily_loss_idr > 0.0 and self.daily_pnl_idr <= -self.max_daily_loss_idr
            )

            indodax_local_allow = bool(indodax_ready and self.indodax_daily_pnl_idr > -indodax_daily_loss_cap_idr)
            phantom_local_allow = bool(phantom_ready and self.phantom_daily_pnl_idr > -phantom_daily_loss_cap_idr)
            indodax_allow_orders = bool(indodax_local_allow and not global_hard_stop)
            phantom_allow_orders = bool(phantom_local_allow and not global_hard_stop)

            indodax_reason = ""
            if not indodax_ready:
                indodax_reason = "indodax_balance_unavailable"
            elif global_hard_stop:
                indodax_reason = (
                    "global_daily_loss_cap_breached "
                    f"({self.daily_pnl_idr:.2f} <= -{self.max_daily_loss_idr:.2f})"
                )
            elif not indodax_allow_orders:
                indodax_reason = (
                    "indodax_daily_loss_cap_breached "
                    f"({self.indodax_daily_pnl_idr:.2f} < -{indodax_daily_loss_cap_idr:.2f})"
                )

            phantom_reason = ""
            if not phantom_ready:
                phantom_reason = "phantom_reconciliation_required"
            elif global_hard_stop:
                phantom_reason = (
                    "global_daily_loss_cap_breached "
                    f"({self.daily_pnl_idr:.2f} <= -{self.max_daily_loss_idr:.2f})"
                )
            elif not phantom_allow_orders:
                phantom_reason = (
                    "phantom_daily_loss_cap_breached "
                    f"({self.phantom_daily_pnl_idr:.2f} < -{phantom_daily_loss_cap_idr:.2f})"
                )

            allow_new_orders = bool(indodax_allow_orders or phantom_allow_orders)
            if global_hard_stop:
                allow_new_orders = False
                allow_reason = (
                    "global_daily_loss_cap_breached "
                    f"({self.daily_pnl_idr:.2f} <= -{self.max_daily_loss_idr:.2f})"
                )
            elif allow_new_orders:
                ready_bits = []
                if indodax_allow_orders:
                    ready_bits.append("indodax")
                if phantom_allow_orders:
                    ready_bits.append("phantom")
                allow_reason = "venue-scoped allowances active: " + ", ".join(ready_bits)
            else:
                blocked_bits = []
                if indodax_reason:
                    blocked_bits.append(f"indodax={indodax_reason}")
                if phantom_reason:
                    blocked_bits.append(f"phantom={phantom_reason}")
                allow_reason = "; ".join(blocked_bits) or "no venue ready for orders"
            self.status = "BLOCKED_WITH_REASON" if global_hard_stop else ("RECONCILED" if allow_new_orders else "DEGRADED")
            
            payload = {
                "date": self.last_reset_date,
                "global_status": self.status,
                "start_total_equity_idr": self.start_total_equity_idr,
                "current_total_equity_idr": self.current_total_equity_idr,
                "max_daily_loss_idr": self.max_daily_loss_idr,
                "daily_pnl_idr": self.daily_pnl_idr,
                "daily_pnl_pct": self.daily_pnl_pct,
                "external_deposits_today": self.external_deposits_today,
                "external_withdrawals_today": self.external_withdrawals_today,
                "reset_deposits_offset": self.reset_deposits_offset,
                "reset_withdrawals_offset": self.reset_withdrawals_offset,
                "in_flight_idr": in_flight_idr,
                "status": self.status,
                "global_hard_stop": global_hard_stop,
                "global_hard_stop_reason": allow_reason if global_hard_stop else "",
                "allow_new_orders": allow_new_orders,
                "allow_new_orders_reason": allow_reason,
                "venues": {
                    "indodax": {
                        "status": "RECONCILED" if indodax_allow_orders else "BLOCKED_WITH_REASON",
                        "equity_idr": indodax_real_balance + indodax_coin_holdings_idr,
                        "start_equity_idr": self.start_indodax_equity_idr,
                        "daily_pnl_idr": self.indodax_daily_pnl_idr,
                        "daily_pnl_pct": self.indodax_daily_pnl_pct,
                        "daily_loss_cap_idr": indodax_daily_loss_cap_idr,
                        "allow_orders": indodax_allow_orders,
                        "reason": indodax_reason,
                    },
                    "phantom": {
                        "status": "RECONCILED" if phantom_allow_orders else "BLOCKED_WITH_REASON",
                        "equity_idr": phantom_equity_idr,
                        "start_equity_idr": self.start_phantom_equity_idr,
                        "daily_pnl_idr": self.phantom_daily_pnl_idr,
                        "daily_pnl_pct": self.phantom_daily_pnl_pct,
                        "daily_loss_cap_idr": phantom_daily_loss_cap_idr,
                        "allow_orders": phantom_allow_orders,
                        "reason": phantom_reason,
                    },
                },
                "allow_indodax_orders": indodax_allow_orders,
                "allow_phantom_orders": phantom_allow_orders,
                "bridge": "ON",
                "withdrawal": "ON",
                "targets": targets,
                "phantom_details": phantom_summary
            }
            self.allow_new_orders = allow_new_orders
            self.allow_new_orders_reason = allow_reason
            self.venue_states = payload.get("venues", {})
            self.targets_snapshot = targets
            self.phantom_details_snapshot = phantom_summary
            self.save()
            return payload
        except Exception as e:
            logger.error(f"❌ Error in reconcile_governor: {e}", exc_info=True)
            self.status = "UNRECONCILED"
            self.save()
            raise e

if __name__ == "__main__":
    import asyncio
    import argparse
    import sys
    
    # Configure logging to stdout
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    )
    
    parser = argparse.ArgumentParser(description="KiBot Capital Governor CLI/Service")
    parser.add_argument("--reset-pnl", action="store_true", help="Trigger manual PnL reset to current reconciled equity")
    args = parser.parse_args()
    
    async def run_governor_service(reset_only=False):
        # Instantiate gateways
        try:
            from Core.Exchange.indodax import IndodaxGateway
            indodax = IndodaxGateway()
        except Exception as e:
            logger.error(f"Failed to import/instantiate IndodaxGateway: {e}")
            indodax = None
            
        try:
            from Core.Exchange.phantom_router import PhantomRouter
            phantom_router = PhantomRouter()
        except Exception as e:
            logger.error(f"Failed to import/instantiate PhantomRouter: {e}")
            phantom_router = None
            
        gov = CapitalGovernor(indodax, phantom_router)
        
        if reset_only:
            logger.info("Executing initial reconciliation to get current consolidated equity...")
            await gov.reconcile_governor()
            gov.manual_pnl_reset()
            logger.info("✅ Manual Daily PnL Reset completed successfully.")
            return

        logger.info("Initializing Capital Governor standalone service loop...")
        # Infinite reconciliation loop (every 10 seconds)
        while True:
            try:
                logger.info("Executing capital reconciliation cycle...")
                res = await gov.reconcile_governor()
                logger.info(
                    f"Consolidated Reconciled: Total Equity Rp{res['current_total_equity_idr']:,.2f} | "
                    f"Daily PnL Rp{res['daily_pnl_idr']:+,.2f} | Date: {res['date']}"
                )
            except Exception as e:
                logger.error(f"Error in reconciliation cycle: {e}", exc_info=True)
            await asyncio.sleep(10)

    try:
        if args.reset_pnl:
            asyncio.run(run_governor_service(reset_only=True))
        else:
            asyncio.run(run_governor_service(reset_only=False))
    except KeyboardInterrupt:
        logger.info("Capital Governor Service stopped by user.")
