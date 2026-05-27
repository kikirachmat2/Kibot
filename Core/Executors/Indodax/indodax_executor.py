#!/usr/bin/env python3
from __future__ import annotations
# from Batam.Support.ki_vault import load_sovereign_env (Removed to allow dynamic loading below)
import sys
import os
import asyncio
import json
import socket
import logging
import time
import signal
from pathlib import Path

# Resolve absolute root
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import logging
from datetime import datetime
from typing import Dict, Any, List

# Local imports
from Core.Exchange.indodax import IndodaxGateway
from Core.risk_gate import RiskGate
from Core.Support.ki_vault import load_sovereign_env
from Core.sovereign_state import load_strategy, check_urgency

# ── Phase 5: Order lifecycle tracking ──
try:
    from Core.Intelligence.order_tracker import get_tracker as _get_tracker
    from Core.Intelligence.exit_plan import (
        build_exit_plan,
        check_partial_tp,
        check_trailing_stop,
        load_plan,
        minimum_profitable_exit_pct,
        minimum_profitable_exit_price,
    )
    from Core.Intelligence.pre_trade_simulator import simulate_indodax_entry
    from Core.Intelligence.decision_journal import log_execution_event, log_pre_trade_simulation
    from Core.Intelligence.trade_history import record_trade_event as _record_trade_event
    _ORDER_TRACKER_AVAILABLE = True
except ImportError:
    _ORDER_TRACKER_AVAILABLE = False
    _record_trade_event = None
    logger_pre = __import__("logging").getLogger("IndodaxExecutor")
    logger_pre.warning("[Executor] order_tracker / exit_plan not available — upgrade to Phase 5")

try:
    load_sovereign_env()
except Exception as e:
    print(f"❌ CRITICAL: Failed to load vault: {e}")
    sys.exit(1)

# Logging Config
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] 🇮🇩 INDO-EXEC - %(levelname)s - %(message)s'
)
logger = logging.getLogger("IndodaxExecutor")


def _emit_trade_history(event_type: str, payload: Dict[str, Any]) -> None:
    if _record_trade_event is None:
        return
    try:
        _record_trade_event(event_type, payload)
    except Exception as exc:
        logger.debug("Trade history emission failed for %s: %s", event_type, exc)

from Core.Support.ki_config import KiConfig
from Core.Trading.autonomous_sizing import AutonomousSizing
LISTEN_PORT = KiConfig.INDO_SIGNAL_PORT
REPORT_PORT = 9997 # Port to report back to Batam

class IndodaxExecutor:
    def __init__(self):
        self.indodax = IndodaxGateway()
        self.risk = RiskGate()
        self.active_trades = {} 
        self.running = False
        self.batam_ip = os.environ.get("KIBOT_MASTER_IP", "127.0.0.1")
        # Canonical runtime state lives in the top-level state/ directory.
        self.state_file = Path(ROOT_DIR) / "state" / "active_trades.json"
        self.lock = asyncio.Lock()
        self.reservations = {} # To prevent race conditions
        self._last_wallet_reconcile = 0.0
        self._wallet_reconcile_interval = float(os.getenv("KIBOT_EXECUTOR_RECONCILE_INTERVAL_S", "60") or 60)
        self.sizing = AutonomousSizing()
        self._load_active_trades()

    def _load_active_trades(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    self.active_trades = json.load(f)
                logger.info(f"📂 Loaded {len(self.active_trades)} active trades from state.")
            except Exception as e:
                logger.error(f"Failed to load active trades: {e}")

    def _save_active_trades(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.state_file, "w") as f:
                json.dump(self.active_trades, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save active trades: {e}")

    async def _ensure_daily_equity_anchor(self) -> float:
        """Ensure starting equity is anchored in daily_equity_anchor.json using live balance."""
        from Core.risk_gate import _today_wib
        today = _today_wib()
        anchor = self.risk._load_equity_anchor()
        if not anchor or anchor.get("date") != today:
            try:
                current_balance = await self.indodax.get_balance("idr")
                if current_balance > 0:
                    self.risk._save_equity_anchor(current_balance)
                    return current_balance
            except Exception as e:
                logger.error(f"Failed to initialize daily equity anchor: {e}")
        return float(anchor.get("start_equity_idr", 0.0))

    def _load_canary_stats(self) -> dict:
        stats_file = Path(ROOT_DIR) / "state" / "canary_daily_stats.json"
        today = datetime.now().strftime("%Y-%m-%d")
        if stats_file.exists():
            try:
                with open(stats_file, "r") as f:
                    data = json.load(f)
                    if data.get("date") == today:
                        return data
            except Exception as e:
                logger.error(f"Failed to load legacy guard stats: {e}")
        return {"date": today, "trade_count": 0, "daily_loss_idr": 0.0}

    def _save_canary_stats(self, stats: dict):
        stats_file = Path(ROOT_DIR) / "state" / "canary_daily_stats.json"
        stats_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(stats_file, "w") as f:
                json.dump(stats, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save legacy guard stats: {e}")

    @staticmethod
    def _exit_cost_basis(trade: Dict[str, Any], exit_amount: float) -> float:
        """Allocate the entry cost basis for the amount actually exited."""
        state_amount = float(trade.get("amount", 0) or 0)
        total_cost = float(trade.get("cost", 0) or 0)
        if state_amount > 0 and total_cost > 0:
            ratio = max(0.0, min(float(exit_amount) / max(state_amount, 1e-9), 1.0))
            return round(total_cost * ratio, 2)
        entry_price = float(trade.get("price", 0) or 0)
        return round(max(0.0, float(exit_amount)) * max(0.0, entry_price), 2)

    @staticmethod
    def _estimate_roundtrip_fee_idr(entry_cost_idr: float, exit_value_idr: float, fee_roundtrip_pct: float) -> float:
        """Estimate total entry+exit fees for the realized slice."""
        fee_rate = max(0.0, float(fee_roundtrip_pct)) / 100.0
        if fee_rate <= 0:
            return 0.0
        fee_base = max(0.0, float(entry_cost_idr) + float(exit_value_idr))
        return round(fee_base * fee_rate / 2.0, 2)

    def _net_exit_result(
        self,
        trade: Dict[str, Any],
        exit_amount: float,
        exit_price: float,
        fee_roundtrip_pct: float,
    ) -> Dict[str, float]:
        """Return fee-aware exit math for a realized slice."""
        exit_amount = max(0.0, float(exit_amount))
        exit_price = max(0.0, float(exit_price))
        exit_value_idr = round(exit_amount * exit_price, 2)
        entry_cost_idr = self._exit_cost_basis(trade, exit_amount)
        gross_pnl_idr = round(exit_value_idr - entry_cost_idr, 2)
        fee_idr = self._estimate_roundtrip_fee_idr(entry_cost_idr, exit_value_idr, fee_roundtrip_pct)
        net_pnl_idr = round(gross_pnl_idr - fee_idr, 2)
        return {
            "entry_cost_idr": entry_cost_idr,
            "exit_value_idr": exit_value_idr,
            "gross_pnl_idr": gross_pnl_idr,
            "fee_idr": fee_idr,
            "net_pnl_idr": net_pnl_idr,
        }

    @staticmethod
    def _allows_loss_exit(reason: str) -> bool:
        """Return True for exits where flattening risk beats waiting for profit."""
        reason_upper = str(reason or "").upper()
        return any(
            marker in reason_upper
            for marker in (
                "HARD_STOP",
                "TRAILING_STOP",
                "MIDNIGHT_DEADLINE",
                "EXIT_ALL",
                "DAILY_ROLLOVER",
                "GLOBAL_DAILY_LOSS_CAP",
                "DISTRIBUTION_SPREAD_EXIT",
                "DISTRIBUTION_OBI_EXIT",
                "MAX_HOLD_EXIT",
            )
        )

    async def _resolve_live_exit_price(self, symbol: str, fallback_price: float = 0.0) -> tuple[float, Dict[str, Any]]:
        """Resolve a practical sell price from live orderbook/ticker."""
        pair = symbol.lower().replace("/", "_")
        if "_" not in pair:
            pair = f"{pair}_idr"

        resolved_price = float(fallback_price or 0.0)
        metadata: Dict[str, Any] = {
            "source": "fallback",
            "fallback_price": resolved_price,
            "pair": pair,
            "best_bid": 0.0,
            "best_ask": 0.0,
            "spread_pct": 0.0,
        }

        try:
            orderbook = await self.indodax.get_orderbook(symbol)
            bids = orderbook.get("bids", []) if isinstance(orderbook, dict) else []
            asks = orderbook.get("asks", []) if isinstance(orderbook, dict) else []
            best_bid = float(bids[0][0]) if bids else 0.0
            best_ask = float(asks[0][0]) if asks else 0.0
            if best_bid > 0:
                resolved_price = best_bid
                metadata.update(
                    {
                        "source": "orderbook_best_bid",
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "spread_pct": ((best_ask - best_bid) / best_bid * 100.0) if best_ask > 0 else 0.0,
                    }
                )
                return resolved_price, metadata
        except Exception as exc:
            metadata["orderbook_error"] = str(exc)

        try:
            ticker = await self.indodax.get_ticker(pair)
            last_price = float(ticker.get("last", 0.0) or 0.0)
            if last_price > 0:
                resolved_price = last_price
                metadata.update({"source": "ticker_last", "ticker_last": last_price})
        except Exception as exc:
            metadata["ticker_error"] = str(exc)

        return resolved_price, metadata

    async def _resolve_live_entry_price(self, symbol: str, fallback_price: float = 0.0) -> tuple[float, Dict[str, Any]]:
        pair = symbol.lower().replace("/", "_")
        if "_" not in pair:
            pair = f"{pair}_idr"

        resolved_price = float(fallback_price or 0.0)
        metadata: Dict[str, Any] = {
            "source": "signal",
            "fallback_price": resolved_price,
            "pair": pair,
        }

        try:
            orderbook = await self.indodax.get_orderbook(symbol)
            bids = orderbook.get("bids", []) if isinstance(orderbook, dict) else []
            asks = orderbook.get("asks", []) if isinstance(orderbook, dict) else []
            best_bid = float(bids[0][0]) if bids else 0.0
            best_ask = float(asks[0][0]) if asks else 0.0
            if best_ask > 0:
                resolved_price = best_ask
                metadata.update({
                    "source": "orderbook_best_ask",
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "spread_pct": ((best_ask - best_bid) / best_bid * 100.0) if best_bid > 0 else 0.0,
                })
                return resolved_price, metadata
            if best_bid > 0:
                resolved_price = best_bid
                metadata.update({
                    "source": "orderbook_best_bid",
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                })
                return resolved_price, metadata
        except Exception as exc:
            metadata["orderbook_error"] = str(exc)

        try:
            ticker = await self.indodax.get_ticker(pair)
            last_price = float(ticker.get("last", 0.0) or 0.0)
            if last_price > 0:
                resolved_price = last_price
                metadata.update({
                    "source": "ticker_last",
                    "ticker_last": last_price,
                })
                return resolved_price, metadata
        except Exception as exc:
            metadata["ticker_error"] = str(exc)

        if resolved_price > 0:
            metadata["source"] = "signal_fallback"
        return resolved_price, metadata


    async def start(self):
        print(f"🚀 {self.__class__.__name__} Starting...")
        logger.info(f"🚦 Live trading enabled: {KiConfig.LIVE_TRADING_ENABLED}")
        asyncio.create_task(self.monitor_positions())
        self.running = True
        logger.info(f"🚀 Indodax Engine active on port {LISTEN_PORT}...")
        
        # Setup UDP Listener with ReuseAddr
        loop = asyncio.get_event_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bind_host = os.getenv("KIBOT_EXECUTOR_BIND_HOST", "127.0.0.1")
        sock.bind((bind_host, LISTEN_PORT))
        
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: SignalProtocol(self),
            sock=sock
        )
        
        # Start Heartbeat
        asyncio.create_task(self.heartbeat_loop())
        
        try:
            while self.running:
                await asyncio.sleep(1)
        finally:
            transport.close()

    async def heartbeat_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        while self.running:
            try:
                status = {
                    "node": os.environ.get("KIBOT_NODE_NAME", "INDODAX_NODE"),
                    "type": "HEARTBEAT",
                    "status": "ONLINE",
                    "timestamp": datetime.now().isoformat(),
                    "active_trades": len(self.active_trades)
                }
                sock.sendto(json.dumps(status).encode(), (self.batam_ip, REPORT_PORT))
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")
            await asyncio.sleep(10)

    async def monitor_positions(self):
        """Pure script-based monitoring for fast Exit/Trailing-Stop."""
        while self.running:
            try:
                now = time.time()
                if now - self._last_wallet_reconcile >= self._wallet_reconcile_interval:
                    await self.reconcile_wallet_positions()
                    self._last_wallet_reconcile = now

                strategy = load_strategy()
                indo_strat = strategy.get("indodax", {})
                daily_state = strategy.get("daily_state", {}) if isinstance(strategy.get("daily_state"), dict) else {}
                green_hold_mode = str(daily_state.get("color", "")).upper() == "GREEN" and bool(daily_state.get("hold_winners", False))
                green_hold_multiplier = float(
                    indo_strat.get("green_hold_tp_multiplier", daily_state.get("take_profit_multiplier", 1.0)) or 1.0
                )
                urgency = check_urgency()
                fee_roundtrip_pct = float(indo_strat.get("fee_roundtrip_pct", 1.02) or 1.02)
                fee_buffer_pct = float(indo_strat.get("fee_buffer_pct", 0.3) or 0.3)

                if urgency.get("flag") == "EMERGENCY_PAUSE":
                    logger.warning(f"🚨 EMERGENCY PAUSE DETECTED: {urgency.get('reason')}")
                else:
                    for symbol, data in list(self.active_trades.items()):
                        pending_entry_order = str(data.get("entry_pending_order_id") or "")
                        pending_entry_amount = float(data.get("amount") or 0.0)
                        if pending_entry_order and pending_entry_amount <= 1e-8:
                            # A buy has been accepted but has not yet appeared in the wallet.
                            # If price has run away, cancel the stale order so the
                            # next cycle can re-evaluate at live market levels.
                            await self._handle_pending_entry(symbol, data)
                            continue
                        if await self._handle_pending_exit(symbol, data, fee_roundtrip_pct):
                            continue

                        blocked_until = float(data.get("exit_blocked_until", 0) or 0)
                        if blocked_until > time.time():
                            continue

                        current_price_data = await self.indodax.get_ticker(symbol.lower().replace("/", "_"))
                        last_price = float(current_price_data.get("last", 0))
                        entry_price = data.get("price")
                        
                        if last_price <= 0: continue

                        change = (last_price - entry_price) / entry_price * 100

                        # Phase 5 exit contract: every real entry should carry a
                        # concrete plan. Use it first, then keep the legacy
                        # strategy thresholds as fallback safety rails.
                        high_price = data.get("high_price", entry_price)
                        if last_price > high_price:
                            self.active_trades[symbol]["high_price"] = last_price
                            high_price = last_price

                        exit_plan = data.get("exit_plan") if isinstance(data.get("exit_plan"), dict) else {}
                        if not exit_plan and data.get("sovereign_order_id") and _ORDER_TRACKER_AVAILABLE:
                            try:
                                exit_plan = load_plan(str(data.get("sovereign_order_id"))) or {}
                            except Exception:
                                exit_plan = {}

                        min_profit_pct = max(
                            float(exit_plan.get("minimum_profitable_exit_pct", 0.0) or 0.0),
                            float(exit_plan.get("breakeven_after_pct", 0.0) or 0.0),
                            minimum_profitable_exit_pct(fee_roundtrip_pct, fee_buffer_pct),
                        )

                        if exit_plan:
                            try:
                                age_min = (time.time() - float(data.get("time", time.time()) or time.time())) / 60.0
                                max_hold_min = float(exit_plan.get("max_hold_minutes", 0) or 0)
                                if max_hold_min > 0 and age_min >= max_hold_min:
                                    logger.info(
                                        f"⏰ EXIT PLAN MAX HOLD: {symbol} age={age_min:.1f}m "
                                        f">= {max_hold_min:.1f}m"
                                    )
                                    await self.execute_exit(symbol, last_price, "MAX_HOLD_EXIT")
                                    continue

                                partial = check_partial_tp(
                                    exit_plan,
                                    last_price,
                                    bool(data.get("partial_tp_done", False)),
                                )
                                if partial.get("should_partial") and float(partial.get("fraction", 0) or 0) > 0:
                                    logger.info(
                                        f"💚 EXIT PLAN PARTIAL: {symbol} {partial.get('reason')} "
                                        f"fraction={float(partial.get('fraction')):.2f}"
                                    )
                                    await self.execute_exit(
                                        symbol,
                                        last_price,
                                        "PARTIAL_TP",
                                        fraction=float(partial.get("fraction", 0.0) or 0.0),
                                    )
                                    continue

                                trail = check_trailing_stop(exit_plan, last_price, high_price)
                                if trail.get("trail_stop_price"):
                                    self.active_trades.setdefault(symbol, {})["trail_stop_price"] = trail.get("trail_stop_price")
                                    self._save_active_trades()
                                if trail.get("should_exit"):
                                    logger.info(f"📉 EXIT PLAN TRIGGER: {symbol} {trail.get('reason')}")
                                    await self.execute_exit(symbol, last_price, str(trail.get("reason") or "EXIT_PLAN"))
                                    continue

                                rules = exit_plan.get("distribution_exit_rules", {}) if isinstance(exit_plan.get("distribution_exit_rules"), dict) else {}
                                spread_limit = float(rules.get("exit_if_spread_above_pct", 0) or 0)
                                obi_limit = float(rules.get("exit_if_obi_below", -999) or -999)
                                if spread_limit > 0 or obi_limit > -999:
                                    try:
                                        ob = await self.indodax.get_orderbook(symbol)
                                        bids = ob.get("bids", [])
                                        asks = ob.get("asks", [])
                                        if bids and asks:
                                            best_bid = float(bids[0][0])
                                            best_ask = float(asks[0][0])
                                            spread_now = ((best_ask - best_bid) / best_bid * 100.0) if best_bid else 99.0
                                            bid_vol = sum(float(row[1]) for row in bids[:5])
                                            ask_vol = sum(float(row[1]) for row in asks[:5])
                                            obi_now = (bid_vol - ask_vol) / max(bid_vol + ask_vol, 1e-9)
                                            if spread_limit > 0 and spread_now >= spread_limit:
                                                logger.info(
                                                    f"🚪 DISTRIBUTION EXIT: {symbol} spread {spread_now:.2f}% >= {spread_limit:.2f}%"
                                                )
                                                await self.execute_exit(symbol, last_price, "DISTRIBUTION_SPREAD_EXIT")
                                                continue
                                            if obi_now <= obi_limit:
                                                logger.info(
                                                    f"🚪 DISTRIBUTION EXIT: {symbol} OBI {obi_now:.2f} <= {obi_limit:.2f}"
                                                )
                                                await self.execute_exit(symbol, last_price, "DISTRIBUTION_OBI_EXIT")
                                                continue
                                    except Exception as ob_err:
                                        logger.debug(f"Distribution exit check skipped for {symbol}: {ob_err}")
                            except Exception as plan_err:
                                logger.warning(f"Exit plan check failed for {symbol}: {plan_err}")

                        # 1. Hard Stop Loss
                        if change <= -indo_strat.get("hard_stop_pct", 1.5):
                            logger.warning(f"🛑 HARD STOP TRIGGERED: {symbol} @ {change:.2f}%")
                            await self.execute_exit(symbol, last_price, "HARD_STOP")
                            continue
                        
                        # 2. Trailing Stop
                        from_high = (high_price - last_price) / high_price * 100
                        if from_high >= indo_strat.get("trailing_stop_pct", 0.25) and change > 0:
                            logger.info(f"📉 TRAILING STOP TRIGGERED: {symbol} @ {from_high:.2f}% from high")
                            await self.execute_exit(symbol, last_price, "TRAILING_STOP")
                            continue

                        # 3. Dynamic Take Profit (V3.2 fallback)
                        base_take_profit_pct = max(float(indo_strat.get("take_profit_pct", 0.5)), min_profit_pct)
                        effective_take_profit_pct = base_take_profit_pct
                        if green_hold_mode:
                            effective_take_profit_pct = base_take_profit_pct * max(1.0, green_hold_multiplier)
                        effective_take_profit_pct = max(effective_take_profit_pct, min_profit_pct)
                        if green_hold_mode and change >= base_take_profit_pct and change < effective_take_profit_pct:
                            logger.debug(
                                f"🟢 GREEN HOLD: {symbol} holding profit @ {change:.2f}% "
                                f"(TP {base_take_profit_pct:.2f}% -> {effective_take_profit_pct:.2f}%)"
                            )

                        if change >= effective_take_profit_pct:
                            target_price = minimum_profitable_exit_price(
                                float(data.get("price") or last_price or 0.0),
                                fee_roundtrip_pct,
                                fee_buffer_pct,
                            )
                            exit_price = max(last_price, target_price) if target_price > 0 else last_price
                            logger.info(
                                f"💰 TAKE PROFIT HIT: {symbol} @ {change:.2f}% "
                                f"(target >= Rp{exit_price:,.0f}, floor={min_profit_pct:.2f}%)"
                            )
                            await self.execute_exit(symbol, exit_price, "TAKE_PROFIT")
                            continue

                        # 4. Midnight Oracle Exit
                        if strategy.get("global_mode") == "EXIT_ALL":
                            logger.info(f"🌑 MIDNIGHT DEADLINE: Liquidating {symbol} for Daily Report.")
                            await self.execute_exit(symbol, last_price, "MIDNIGHT_DEADLINE")

            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
            finally:
                # Scan for stale orders every cycle
                if _ORDER_TRACKER_AVAILABLE:
                    try:
                        staled = _get_tracker().scan_stale()
                        if staled:
                            logger.warning(f"[Executor] {len(staled)} order(s) marked STALE: {staled}")
                    except Exception:
                        pass
                await asyncio.sleep(5)

    @staticmethod
    def _extract_orders(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Normalize Indodax openOrders return shapes into a flat order list."""
        if not isinstance(payload, dict):
            return []
        raw = payload.get("return", payload)
        if isinstance(raw, dict):
            orders = raw.get("orders", raw.get("order", []))
            if isinstance(orders, dict):
                flattened = []
                for item in orders.values():
                    if isinstance(item, list):
                        flattened.extend([x for x in item if isinstance(x, dict)])
                    elif isinstance(item, dict):
                        flattened.append(item)
                return flattened
            if isinstance(orders, list):
                return [x for x in orders if isinstance(x, dict)]
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
        return []

    @staticmethod
    def _order_matches(order: Dict[str, Any], *, order_id: str = "", side: str = "") -> bool:
        if not isinstance(order, dict):
            return False
        if order_id:
            candidate = str(order.get("order_id") or order.get("id") or "")
            if candidate and candidate != order_id:
                return False
        if side:
            order_side = str(order.get("type") or order.get("side") or "").lower()
            if order_side and order_side != side.lower():
                return False
        return True

    async def _handle_pending_entry(self, symbol: str, data: Dict[str, Any]) -> bool:
        """Cancel stale entry orders whose price has drifted away from the market."""
        pending_entry_order_id = str(data.get("entry_pending_order_id") or "").strip()
        if not pending_entry_order_id:
            return False

        pending_amount = float(data.get("amount") or 0.0)
        if pending_amount > 1e-8:
            return False

        pair = symbol.lower().replace("/", "_")
        if "_" not in pair:
            pair = f"{pair}_idr"

        try:
            open_orders = self._extract_orders(await self.indodax.get_open_orders(pair))
        except Exception as exc:
            logger.debug(f"[Executor] openOrders check failed for pending entry {symbol}: {exc}")
            return False

        exchange_order_id = str(data.get("entry_pending_exchange_order_id") or "").strip()
        matching_order = None
        for order in open_orders:
            if self._order_matches(order, order_id=exchange_order_id or pending_entry_order_id, side="buy"):
                matching_order = order
                break

        if not matching_order:
            # Let wallet reconciliation clear it if the exchange no longer knows
            # about the order. We only cancel orders that are still open.
            return False

        pending_price = float(data.get("entry_pending_price") or data.get("price") or 0.0)
        pending_since = float(data.get("entry_pending_since") or data.get("time") or time.time())
        age_sec = max(0.0, time.time() - pending_since)

        current_ref_price = 0.0
        best_ask = 0.0
        best_bid = 0.0
        try:
            orderbook = await self.indodax.get_orderbook(symbol)
            bids = orderbook.get("bids", []) or []
            asks = orderbook.get("asks", []) or []
            if bids:
                best_bid = float(bids[0][0])
            if asks:
                best_ask = float(asks[0][0])
            current_ref_price = best_ask or best_bid
        except Exception as ob_err:
            logger.debug(f"[Executor] orderbook fetch failed for pending entry {symbol}: {ob_err}")

        if current_ref_price <= 0:
            try:
                ticker = await self.indodax.get_ticker(pair)
                current_ref_price = float(ticker.get("last", 0.0) or 0.0)
            except Exception as tick_err:
                logger.debug(f"[Executor] ticker fetch failed for pending entry {symbol}: {tick_err}")

        drift_pct = 0.0
        if pending_price > 0 and current_ref_price > 0:
            drift_pct = ((current_ref_price - pending_price) / pending_price) * 100.0

        strategy = load_strategy()
        indo_strat = strategy.get("indodax", {})
        cancel_gap_pct = float(
            indo_strat.get(
                "entry_pending_cancel_gap_pct",
                os.getenv("KIBOT_ENTRY_PENDING_CANCEL_GAP_PCT", "2.0"),
            )
            or 2.0
        )
        max_age_sec = float(
            indo_strat.get(
                "entry_pending_max_age_sec",
                os.getenv("KIBOT_ENTRY_PENDING_MAX_AGE_SEC", "120"),
            )
            or 120
        )

        if age_sec < max_age_sec and drift_pct < cancel_gap_pct:
            data["entry_pending_last_seen"] = time.time()
            data["entry_pending_status"] = "OPEN"
            self._save_active_trades()
            return True

        reason_bits = [
            f"age={age_sec:.0f}s>=max{max_age_sec:.0f}s" if age_sec >= max_age_sec else "",
            f"market_drift={drift_pct:.2f}%>=gap{cancel_gap_pct:.2f}%" if drift_pct >= cancel_gap_pct else "",
        ]
        reason = "; ".join(bit for bit in reason_bits if bit) or "pending_entry_stale"
        logger.warning(
            "🛑 CANCELING STALE ENTRY: %s pending buy %s @ %.0f is stale (%s); market ref=%.0f bid=%.0f ask=%.0f",
            symbol,
            pending_entry_order_id,
            pending_price,
            reason,
            current_ref_price,
            best_bid,
            best_ask,
        )

        sovereign_order_id = str(data.get("sovereign_order_id") or "").strip()
        tracker = None
        if _ORDER_TRACKER_AVAILABLE and sovereign_order_id:
            try:
                tracker = _get_tracker()
                current_record = tracker.load(sovereign_order_id) or {}
                current_state = str(current_record.get("state") or "").upper()
                if current_state not in {"STALE", "CANCEL_REQUESTED", "CANCELLED", "FAILED"}:
                    tracker.transition(
                        sovereign_order_id,
                        "STALE",
                        note=reason,
                        trade_history_payload={
                            "reason": reason,
                            "source": "indodax_executor",
                        },
                    )
            except Exception as tracker_err:
                logger.debug(f"[Executor] tracker stale transition failed for {symbol}: {tracker_err}")

        cancel_target = exchange_order_id or pending_entry_order_id
        cancel_result: Dict[str, Any] = {}
        try:
            cancel_result = await self.indodax.cancel_order(symbol, cancel_target, "buy")
        except Exception as cancel_err:
            logger.warning(f"🛑 Pending entry cancel request failed for {symbol}: {cancel_err}")
            cancel_result = {"success": 0, "error": str(cancel_err)}

        if cancel_result.get("success") == 1:
            logger.info(f"✅ CANCELED STALE ENTRY: {symbol} order {cancel_target} cancelled")
            if tracker and sovereign_order_id:
                try:
                    tracker.transition(
                        sovereign_order_id,
                        "CANCELLED",
                        note=reason,
                        trade_history_payload={
                            "reason": reason,
                            "source": "indodax_executor",
                        },
                    )
                except Exception as tracker_err:
                    logger.debug(f"[Executor] tracker cancel transition failed for {symbol}: {tracker_err}")

            _emit_trade_history("ORDER_STALE", {
                "source": "indodax_executor",
                "venue": "indodax",
                "symbol": symbol,
                "pair": pair,
                "side": "BUY",
                "status": "STALE",
                "order_id": cancel_target,
                "price_idr": pending_price,
                "amount_idr": float(data.get("entry_pending_budget_idr") or data.get("cost") or 0.0),
                "trade_profile": data.get("trade_profile", "STANDARD"),
                "lifecycle": data.get("lifecycle"),
                "reason": reason,
            })

            trade = self.active_trades.get(symbol, {})
            for key in [
                "entry_pending_order_id",
                "entry_pending_exchange_order_id",
                "entry_pending_budget_idr",
                "entry_pending_price",
                "entry_pending_status",
                "entry_pending_since",
                "entry_pending_reason",
                "entry_pending_last_seen",
                "sovereign_order_id",
            ]:
                trade.pop(key, None)
            trade["entry_pending_cancelled_at"] = time.time()
            trade["entry_pending_cancel_reason"] = reason
            if not float(trade.get("amount") or 0.0):
                # No filled coin exists yet, so the stale entry can be fully removed.
                self.active_trades.pop(symbol, None)
            self._save_active_trades()
            self.report_to_batam(symbol, "ENTRY_CANCELLED", f"Stale pending buy cancelled: {reason}")
            return True

        if tracker and sovereign_order_id:
            try:
                current_record = tracker.load(sovereign_order_id) or {}
                current_state = str(current_record.get("state") or "").upper()
                if current_state not in {"STALE", "CANCEL_REQUESTED", "CANCELLED", "FAILED"}:
                    tracker.transition(
                        sovereign_order_id,
                        "CANCEL_REQUESTED",
                        note=f"{reason} | cancel_failed",
                    )
            except Exception as tracker_err:
                logger.debug(f"[Executor] tracker cancel-request transition failed for {symbol}: {tracker_err}")

        trade = self.active_trades.setdefault(symbol, {})
        trade["entry_pending_status"] = "CANCEL_FAILED"
        trade["entry_pending_last_seen"] = time.time()
        trade["entry_pending_reason"] = reason
        trade["entry_pending_cancel_error"] = str(cancel_result.get("error") or "cancel_failed")
        self._save_active_trades()
        return True

    async def _handle_pending_exit(self, symbol: str, data: Dict[str, Any], fee_roundtrip_pct: float = 1.02) -> bool:
        """Keep pending exits honest until Indodax confirms the asset really left the wallet."""
        order_id = str(data.get("exit_pending_order_id") or "")
        if not order_id:
            return False

        pair = symbol.lower().replace("/", "_")
        if "_" not in pair:
            pair = f"{pair}_idr"
        coin_symbol = pair.split("_")[0]

        live_amount = await self.indodax.get_balance(coin_symbol)
        pending_amount = float(data.get("exit_pending_amount") or data.get("amount") or 0.0)
        exit_price = float(data.get("exit_pending_price") or 0.0)
        entry_price = float(data.get("price") or 0.0)
        pending_reason = str(data.get("exit_pending_reason") or "PENDING_EXIT_REPRICE")
        pending_fraction = float(data.get("exit_pending_fraction") or 1.0)
        pending_since = float(data.get("exit_pending_since") or time.time())
        age_sec = max(0.0, time.time() - pending_since)

        orders = self._extract_orders(await self.indodax.get_open_orders(pair))
        matching_open_order = next(
            (order for order in orders if self._order_matches(order, order_id=order_id, side="sell")),
            None,
        )
        if matching_open_order:
            strategy = load_strategy()
            indo_strat = strategy.get("indodax", {}) if isinstance(strategy, dict) else {}
            max_age_sec = float(
                indo_strat.get(
                    "exit_pending_max_age_sec",
                    os.getenv("KIBOT_EXIT_PENDING_MAX_AGE_SEC", "90"),
                )
                or 90
            )
            reprice_gap_pct = float(
                indo_strat.get(
                    "exit_pending_reprice_gap_pct",
                    os.getenv("KIBOT_EXIT_PENDING_REPRICE_GAP_PCT", "0.5"),
                )
                or 0.5
            )
            live_exit_price, price_meta = await self._resolve_live_exit_price(symbol, exit_price)
            desired_price = live_exit_price or exit_price
            if entry_price > 0 and not self._allows_loss_exit(pending_reason):
                floor_price = minimum_profitable_exit_price(
                    entry_price,
                    fee_roundtrip_pct,
                    float(indo_strat.get("exit_profit_buffer_pct", 0.3) or 0.3),
                )
                desired_price = max(desired_price, floor_price)

            price_gap_pct = 0.0
            if exit_price > 0 and desired_price > 0:
                price_gap_pct = abs(desired_price - exit_price) / exit_price * 100.0
            should_reprice = bool(age_sec >= max_age_sec or price_gap_pct >= reprice_gap_pct)

            if not should_reprice:
                self.active_trades.setdefault(symbol, {}).update({
                    "amount": live_amount or pending_amount or float(data.get("amount") or 0.0),
                    "exit_blocked_until": time.time() + 30,
                    "exit_blocked_reason": f"EXIT_ORDER_OPEN:{order_id}",
                    "exit_pending_last_seen": time.time(),
                    "exit_pending_price_meta": price_meta,
                })
                self._save_active_trades()
                return True

            cancel_result: Dict[str, Any] = {}
            try:
                cancel_result = await self.indodax.cancel_order(symbol, order_id, "sell")
            except Exception as cancel_err:
                cancel_result = {"success": 0, "error": str(cancel_err)}

            if cancel_result.get("success") != 1:
                logger.warning(
                    "⚠️ EXIT REPRICE CANCEL FAILED: %s order %s age=%.0fs gap=%.2f%% err=%s",
                    symbol,
                    order_id,
                    age_sec,
                    price_gap_pct,
                    cancel_result.get("error") or cancel_result,
                )
                self.active_trades.setdefault(symbol, {}).update({
                    "exit_blocked_until": time.time() + 30,
                    "exit_blocked_reason": f"EXIT_CANCEL_FAILED:{order_id}",
                    "exit_pending_last_seen": time.time(),
                    "exit_pending_reprice_error": str(cancel_result.get("error") or cancel_result),
                })
                self._save_active_trades()
                return True

            logger.warning(
                "🔁 EXIT REPRICE: %s cancelled stale sell %s @ %.8g age=%.0fs gap=%.2f%% -> %.8g",
                symbol,
                order_id,
                exit_price,
                age_sec,
                price_gap_pct,
                desired_price,
            )
            trade = self.active_trades.setdefault(symbol, {})
            for key in [
                "exit_pending_order_id",
                "exit_pending_amount",
                "exit_pending_price",
                "exit_pending_reason",
                "exit_pending_fraction",
                "exit_pending_since",
                "exit_pending_last_seen",
                "exit_blocked_reason",
            ]:
                trade.pop(key, None)
            trade["amount"] = live_amount or pending_amount or float(data.get("amount") or 0.0)
            trade["last_exit_reprice_at"] = time.time()
            trade["last_exit_reprice_from"] = exit_price
            trade["last_exit_reprice_to"] = desired_price
            trade["last_exit_reprice_reason"] = f"age={age_sec:.0f}s gap={price_gap_pct:.2f}%"
            self._save_active_trades()
            _emit_trade_history("EXIT_REPRICED", {
                "source": "indodax_executor",
                "venue": "indodax",
                "symbol": symbol,
                "pair": pair,
                "side": "SELL",
                "status": "REPRICED",
                "order_id": order_id,
                "price_idr": desired_price,
                "entry_price_idr": entry_price,
                "exit_price_idr": desired_price,
                "amount_coin": trade["amount"],
                "amount_idr": desired_price * trade["amount"],
                "reason": pending_reason,
                "note": f"cancelled stale exit age={age_sec:.0f}s gap={price_gap_pct:.2f}%",
            })
            await self.execute_exit(symbol, desired_price, pending_reason, pending_fraction)
            return True

        if live_amount <= 1e-8:
            if pending_amount > 0 and exit_price > 0 and entry_price > 0:
                math_result = self._net_exit_result(data, pending_amount, exit_price, fee_roundtrip_pct)
                self.risk.update_pnl(math_result["net_pnl_idr"])
                if KiConfig.CANARY_LIVE_ENABLED and math_result["net_pnl_idr"] < 0:
                    stats = self._load_canary_stats()
                    stats["daily_loss_idr"] += abs(math_result["net_pnl_idr"])
                    self._save_canary_stats(stats)
                    logger.info(f"📉 CANARY STATS: Daily loss updated to Rp{stats['daily_loss_idr']:,.0f}")
            logger.info(f"✅ EXIT FILLED: {symbol} pending order {order_id} settled; state cleared.")

            self.active_trades.pop(symbol, None)
            self._save_active_trades()
            if pending_amount > 0 and exit_price > 0 and entry_price > 0:
                math_result = self._net_exit_result(data, pending_amount, exit_price, fee_roundtrip_pct)
                _emit_trade_history("SELL_FILLED", {
                    "source": "indodax_executor",
                    "venue": "indodax",
                    "symbol": symbol,
                    "pair": pair,
                    "side": "SELL",
                    "status": "FILLED",
                    "order_id": order_id,
                    "price_idr": exit_price,
                    "entry_price_idr": entry_price,
                    "exit_price_idr": exit_price,
                    "amount_coin": pending_amount,
                    "amount_idr": math_result["exit_value_idr"],
                    "fee_idr": math_result["fee_idr"],
                    "gross_realized_pnl_idr": math_result["gross_pnl_idr"],
                    "net_realized_pnl_idr": math_result["net_pnl_idr"],
                    "realized_pnl_idr": math_result["net_pnl_idr"],
                    "realized_pnl_pct": (math_result["net_pnl_idr"] / max(math_result["entry_cost_idr"], 1e-9)) * 100.0,
                    "reason": "pending_exit_settled",
                    "trade_profile": data.get("trade_profile", "STANDARD"),
                    "lifecycle": data.get("lifecycle"),
                })
            self.report_to_batam(symbol, "EXIT_FILLED", f"Pending exit filled @ {exit_price}")
            return True

        state_amount = float(data.get("amount") or live_amount)
        if pending_amount > 0 and live_amount < state_amount and exit_price > 0 and entry_price > 0:
            filled_amount = max(0.0, state_amount - live_amount)
            math_result = self._net_exit_result(data, filled_amount, exit_price, fee_roundtrip_pct)
            self.risk.update_pnl(math_result["net_pnl_idr"])
            if KiConfig.CANARY_LIVE_ENABLED and math_result["net_pnl_idr"] < 0:
                stats = self._load_canary_stats()
                stats["daily_loss_idr"] += abs(math_result["net_pnl_idr"])
                self._save_canary_stats(stats)
                logger.info(f"📉 CANARY STATS: Daily loss updated to Rp{stats['daily_loss_idr']:,.0f}")
            logger.info(
                f"✅ PARTIAL EXIT FILLED: {symbol} pending order {order_id} settled; "
                f"remaining={live_amount:.8f}"
            )

            remaining_cost = max(
                0.0,
                float(data.get("cost", 0.0) or 0.0) * (live_amount / max(state_amount, 1e-9)),
            )
            trade = self.active_trades.setdefault(symbol, {})
            trade.update({
                "amount": live_amount,
                "cost": remaining_cost,
                "partial_tp_done": True,
            })
            for key in [
                "exit_pending_order_id",
                "exit_pending_amount",
                "exit_pending_price",
                "exit_pending_reason",
                "exit_pending_fraction",
                "exit_pending_since",
            ]:
                trade.pop(key, None)
            self._save_active_trades()
            _emit_trade_history("SELL_FILLED", {
                "source": "indodax_executor",
                "venue": "indodax",
                "symbol": symbol,
                "pair": pair,
                "side": "SELL",
                "status": "FILLED",
                "order_id": order_id,
                "price_idr": exit_price,
                "entry_price_idr": entry_price,
                "exit_price_idr": exit_price,
                "amount_coin": filled_amount,
                "amount_idr": math_result["exit_value_idr"],
                "fee_idr": math_result["fee_idr"],
                "gross_realized_pnl_idr": math_result["gross_pnl_idr"],
                "net_realized_pnl_idr": math_result["net_pnl_idr"],
                "realized_pnl_idr": math_result["net_pnl_idr"],
                "realized_pnl_pct": (math_result["net_pnl_idr"] / max(math_result["entry_cost_idr"], 1e-9)) * 100.0,
                "reason": "partial_exit_settled",
                "trade_profile": data.get("trade_profile", "STANDARD"),
                "lifecycle": data.get("lifecycle"),
            })
            self.report_to_batam(symbol, "PARTIAL_EXIT_FILLED", f"Partial exit filled @ {exit_price}")
            return True

        # Order is gone but the balance remains. It was cancelled/expired or not
        # actually filled. Clear pending markers and let normal exit rules retry.
        logger.warning(
            f"⚠️ EXIT PENDING CLEARED: {symbol} order {order_id} no longer open, "
            f"but live balance remains {live_amount:.8f} {coin_symbol.upper()}."
        )
        trade = self.active_trades.setdefault(symbol, {})
        for key in [
            "exit_pending_order_id",
            "exit_pending_amount",
            "exit_pending_price",
            "exit_pending_reason",
            "exit_pending_since",
        ]:
            trade.pop(key, None)
        trade["amount"] = live_amount
        self._save_active_trades()
        return False

    async def reconcile_wallet_positions(self):
        """
        Make `active_trades.json` follow the exchange wallet, not wishful state.

        This protects the council from blind spots: if a sell did not fill, the
        holding is re-attached; if a stale state has no wallet/open-order backing,
        it is removed before PnL and daily color are computed.
        """
        try:
            info = await self.indodax.get_info()
            if info.get("success") != 1:
                return

            balances = info.get("return", {}).get("balance", {}) or {}
            
            try:
                live_idr = float(balances.get("idr", 0.0) or 0.0)
                if live_idr > 0:
                    from Core.risk_gate import _today_wib
                    today = _today_wib()
                    anchor = self.risk._load_equity_anchor()
                    if not anchor or anchor.get("date") != today:
                        self.risk._save_equity_anchor(live_idr)
            except Exception as e:
                logger.error(f"Failed to update daily equity anchor during reconcile: {e}")

            changed = False

            async with self.lock:
                # Existing active trades must be backed by a live wallet balance
                # or an open order. Otherwise they are stale ghosts.
                for symbol, data in list(self.active_trades.items()):
                    pair = symbol.lower().replace("/", "_")
                    if "_" not in pair:
                        pair = f"{pair}_idr"
                    coin = pair.split("_")[0]
                    live_amount = float(balances.get(coin, 0.0) or 0.0)
                    pending_entry_order_id = str(data.get("entry_pending_order_id") or "")
                    if pending_entry_order_id:
                        open_orders = self._extract_orders(await self.indodax.get_open_orders(pair))
                        pending_price = float(data.get("entry_pending_price") or data.get("price") or 0.0)
                        pending_budget = float(data.get("entry_pending_budget_idr") or data.get("cost") or 0.0)
                        if live_amount <= 1e-8:
                            if open_orders:
                                data["entry_pending_status"] = "OPEN"
                                data["entry_pending_last_seen"] = time.time()
                                changed = True
                                continue
                            logger.warning(f"🧹 RECONCILE: removing stale pending {symbol}; no live balance/open orders.")
                            self.active_trades.pop(symbol, None)
                            changed = True
                            continue

                        desired_state = "PARTIAL_FILL" if open_orders else "FILLED"
                        trade = self.active_trades.setdefault(symbol, {})
                        trade.update({
                            "amount": live_amount,
                            "cost": pending_budget if pending_budget > 0 else live_amount * max(pending_price, 1e-9),
                            "price": pending_price or float(trade.get("price") or 0.0),
                            "high_price": max(float(trade.get("high_price", pending_price or live_amount) or 0.0), pending_price or live_amount),
                            "entry_pending_status": desired_state,
                            "entry_pending_last_seen": time.time(),
                        })
                        if desired_state == "FILLED" and not open_orders:
                            trade["entry_pending_resolved_at"] = time.time()
                            for key in [
                                "entry_pending_order_id",
                                "entry_pending_exchange_order_id",
                                "entry_pending_budget_idr",
                                "entry_pending_price",
                                "entry_pending_reason",
                                "entry_pending_since",
                                "entry_pending_status",
                                "entry_pending_last_seen",
                            ]:
                                trade.pop(key, None)
                        if _ORDER_TRACKER_AVAILABLE and data.get("sovereign_order_id"):
                            try:
                                tracker = _get_tracker()
                                current_record = tracker.load(str(data.get("sovereign_order_id"))) or {}
                                current_state = str(current_record.get("state") or "").upper()
                                if current_state in {"CREATED", "SUBMITTED", "ACCEPTED", "PARTIAL_FILL"} and current_state != desired_state:
                                    tracker.transition(
                                        str(data.get("sovereign_order_id")),
                                        desired_state,
                                        fill_price=pending_price or float(trade.get("price") or 0.0),
                                        coin_amount=live_amount,
                                        note="wallet delta confirmed during reconcile",
                                    )
                            except Exception as ot_err:
                                logger.warning(f"[Executor] Pending entry tracker reconcile failed for {symbol}: {ot_err}")
                        changed = True
                        continue
                    if live_amount <= 1e-8:
                        orders = self._extract_orders(await self.indodax.get_open_orders(pair))
                        if orders:
                            data["exit_blocked_until"] = time.time() + 60
                            data["exit_blocked_reason"] = "OPEN_ORDER_PRESENT_DURING_RECONCILE"
                        else:
                            logger.warning(f"🧹 RECONCILE: removing stale {symbol}; no live balance/open orders.")
                            self.active_trades.pop(symbol, None)
                        changed = True
                        continue

                    state_amount = float(data.get("amount", 0.0) or 0.0)
                    if abs(state_amount - live_amount) / max(live_amount, state_amount, 1e-9) > 0.002:
                        logger.info(
                            f"🔄 RECONCILE: {symbol} amount adjusted "
                            f"{state_amount:.8f} -> {live_amount:.8f}"
                        )
                        data["amount"] = live_amount
                        entry_price = float(data.get("price", 0.0) or 0.0)
                        current_cost = float(data.get("cost", 0.0) or 0.0)
                        expected_cost = live_amount * entry_price if entry_price > 0 else 0.0
                        if expected_cost > 0 and (
                            current_cost <= 0
                            or current_cost < expected_cost * 0.5
                            or current_cost > expected_cost * 1.5
                        ):
                            data["cost"] = expected_cost
                            data["cost_reconciled_reason"] = "wallet_amount_changed_cost_basis_repaired"
                            logger.info(
                                f"🔄 RECONCILE: {symbol} cost basis repaired "
                                f"Rp{current_cost:,.0f} -> Rp{expected_cost:,.0f}"
                            )
                        last_price = float(data.get("last_price", 0.0) or data.get("price", 0.0) or 0.0)
                        if last_price > 0:
                            try:
                                pair_info = await self.indodax.get_pair_info(pair)
                                min_base = float(pair_info.get("trade_min_base_currency", 10_000) or 10_000)
                                min_coin = float(pair_info.get("trade_min_traded_currency", 0) or 0)
                                if live_amount * last_price >= min_base and (not min_coin or live_amount >= min_coin):
                                    stale_reason = str(data.get("exit_blocked_reason") or "")
                                    if stale_reason.startswith("EXIT_MINIMUM_NOT_MET"):
                                        data.pop("exit_blocked_reason", None)
                                        data.pop("exit_blocked_until", None)
                            except Exception:
                                pass
                        changed = True

                # Wallet holdings that are large enough to trade must be visible
                # to the council/executor even if they were created outside this
                # process or survived a restart/order mismatch.
                known_coins = {
                    symbol.lower().replace("/", "_").split("_")[0]
                    for symbol in self.active_trades.keys()
                }
                for coin, raw_amount in balances.items():
                    coin = str(coin or "").lower()
                    if coin == "idr" or coin in known_coins:
                        continue
                    try:
                        amount = float(raw_amount or 0.0)
                    except Exception:
                        continue
                    if amount <= 1e-8:
                        continue

                    pair = f"{coin}_idr"
                    ticker = await self.indodax.get_ticker(pair)
                    price = float(ticker.get("last", 0.0) or 0.0)
                    if price <= 0:
                        continue

                    pair_info = await self.indodax.get_pair_info(pair)
                    min_base = float(pair_info.get("trade_min_base_currency", 10_000) or 10_000)
                    min_coin = float(pair_info.get("trade_min_traded_currency", 0) or 0)
                    value_idr = amount * price
                    if value_idr < min_base or (min_coin and amount < min_coin):
                        continue

                    symbol = f"{coin.upper()}/IDR"
                    self.active_trades[symbol] = {
                        "price": price,
                        "amount": amount,
                        "high_price": price,
                        "time": time.time(),
                        "cost": value_idr,
                        "trade_profile": "WALLET_RECONCILED",
                        "learning_probe": False,
                        "reconciled_at": datetime.now().isoformat(),
                    }
                    logger.warning(
                        f"🔄 RECONCILE: attached wallet holding {symbol} "
                        f"{amount:.8f} worth Rp{value_idr:,.0f}"
                    )
                    changed = True

                if changed:
                    self._save_active_trades()
        except Exception as e:
            logger.error(f"Wallet reconcile failed: {e}")

    async def execute_exit(self, symbol, price, reason, fraction: float = 1.0):
        """Unified exit logic with reporting to Batam."""
        pair = symbol.lower().replace("/", "_")
        if "_" not in pair: pair = f"{pair}_idr"
        
        trade = self.active_trades.get(symbol, {})
        coin_symbol = pair.split("_")[0]
        state_amount = float(trade.get("amount", 0) or 0)
        live_amount = await self.indodax.get_balance(coin_symbol)
        full_amount = min(state_amount, live_amount) if live_amount > 0 else state_amount
        is_partial = 0.0 < float(fraction or 1.0) < 0.999
        amount = full_amount * max(0.0, min(float(fraction or 1.0), 1.0))
        
        if amount <= 0:
            logger.warning(f"⚠️ EXIT SKIPPED: No live amount for {symbol}; removing stale state.")
            self.active_trades.pop(symbol, None)
            self._save_active_trades()
            return

        pair_info = await self.indodax.get_pair_info(pair)
        min_coin = float(pair_info.get("trade_min_traded_currency", 0) or 0)
        min_base = float(pair_info.get("trade_min_base_currency", 10_000) or 10_000)
        if int(pair_info.get("is_maintenance", 0) or 0) == 1 or int(pair_info.get("is_market_suspended", 0) or 0) == 1:
            reason_text = (
                f"EXIT_ROUTE_TEMPORARILY_UNAVAILABLE: {pair} maintenance="
                f"{pair_info.get('is_maintenance')} suspended={pair_info.get('is_market_suspended')}"
            )
            logger.warning(f"⚠️ {symbol} exit blocked: {reason_text}")
            self.active_trades.setdefault(symbol, {}).update({
                "amount": amount,
                "exit_blocked_until": time.time() + 1800,
                "exit_blocked_reason": reason_text,
                "route_status": "BLOCKED_WITH_REASON",
            })
            self._save_active_trades()
            _emit_trade_history("EXIT_REJECTED", {
                "source": "indodax_executor",
                "venue": "indodax",
                "symbol": symbol,
                "pair": pair,
                "side": "SELL",
                "status": "REJECTED",
                "reason": reason_text,
                "price_idr": price,
                "amount_coin": amount,
                "amount_idr": price * amount,
                "trade_profile": trade.get("trade_profile", "STANDARD"),
                "lifecycle": trade.get("lifecycle"),
            })
            return
        strategy = load_strategy()
        indo_strat = strategy.get("indodax", {}) if isinstance(strategy, dict) else {}
        fee_roundtrip_pct = float(indo_strat.get("fee_roundtrip_pct", 1.02) or 1.02)
        entry_price = float(trade.get("price", price) or price or 0.0)
        profitable_floor_price = minimum_profitable_exit_price(
            entry_price,
            fee_roundtrip_pct,
            float(indo_strat.get("exit_profit_buffer_pct", 0.3) or 0.3),
        )
        if profitable_floor_price > 0 and not self._allows_loss_exit(reason):
            if price < profitable_floor_price:
                logger.info(
                    f"🧠 EXIT DEFERRED: {symbol} reason={reason} price Rp{price:,.0f} < profitable floor Rp{profitable_floor_price:,.0f}"
                )
                self.active_trades.setdefault(symbol, {}).update({
                    "last_exit_floor_price": profitable_floor_price,
                    "last_exit_deferred_reason": reason,
                    "exit_blocked_until": time.time() + 30,
                })
                self._save_active_trades()
                return
            price = max(price, profitable_floor_price)
        if (min_coin and amount < min_coin) or (amount * price < min_base):
            if is_partial:
                reason_text = (
                    f"PARTIAL_EXIT_MINIMUM_NOT_MET: partial {amount:.8f} {coin_symbol.upper()} "
                    f"worth Rp{amount * price:,.0f}; keeping full position under trailing plan"
                )
                logger.warning(f"⚠️ {symbol} partial exit skipped: {reason_text}")
                self.active_trades.setdefault(symbol, {}).update({
                    "partial_tp_done": True,
                    "partial_tp_blocked_reason": reason_text,
                    "exit_blocked_until": time.time() + 120,
                })
                self._save_active_trades()
                return
            reason_text = (
                f"EXIT_MINIMUM_NOT_MET: live {amount:.8f} {coin_symbol.upper()} "
                f"worth Rp{amount * price:,.0f}; min coin {min_coin:g}, min base Rp{min_base:,.0f}"
            )
            logger.warning(f"⚠️ {symbol} exit blocked: {reason_text}")
            self.active_trades.setdefault(symbol, {}).update({
                "amount": amount,
                "exit_blocked_until": time.time() + 900,
                "exit_blocked_reason": reason_text,
            })
            self._save_active_trades()
            return

        res = await self.indodax.trade(pair=pair, type="sell", price=price, amount_coin=amount)
        
        if res.get("success") == 1:
            trade_data = res.get("return", {}) if isinstance(res.get("return"), dict) else {}
            order_id = str(trade_data.get("order_id") or trade_data.get("orderId") or "")
            await asyncio.sleep(1.5)

            open_orders = self._extract_orders(await self.indodax.get_open_orders(pair))
            live_after = await self.indodax.get_balance(coin_symbol)
            filled_amount = max(0.0, live_amount - live_after)
            sell_still_open = bool(order_id and any(
                self._order_matches(order, order_id=order_id, side="sell") for order in open_orders
            ))

            if sell_still_open:
                logger.info(f"⏳ EXIT PENDING: {symbol} sell order {order_id} accepted but still open.")
                self.active_trades.setdefault(symbol, {}).update({
                    "amount": full_amount,
                    "exit_pending_order_id": order_id,
                    "exit_pending_amount": amount,
                    "exit_pending_price": price,
                    "exit_pending_reason": reason,
                    "exit_pending_fraction": fraction,
                    "exit_pending_since": time.time(),
                    "exit_blocked_until": time.time() + 60,
                    "exit_blocked_reason": f"EXIT_ORDER_OPEN:{order_id}",
                })
                self._save_active_trades()
                _emit_trade_history("EXIT_PENDING", {
                    "source": "indodax_executor",
                    "venue": "indodax",
                    "symbol": symbol,
                    "pair": pair,
                    "side": "SELL",
                    "status": "PENDING",
                    "order_id": order_id,
                    "price_idr": price,
                    "amount_coin": amount,
                    "amount_idr": price * amount,
                    "reason": reason,
                    "trade_profile": trade.get("trade_profile", "STANDARD"),
                    "lifecycle": trade.get("lifecycle"),
                })
                self.report_to_batam(symbol, "EXIT_PENDING", f"Sell order open @ {price}")
                return

            if filled_amount <= max(1e-8, amount * 0.005) and live_after > 1e-8:
                logger.warning(
                    f"⚠️ EXIT ACCEPTED WITHOUT WALLET DELTA: {symbol}; keeping state. "
                    f"live_before={live_amount:.8f}, live_after={live_after:.8f}"
                )
                self.active_trades.setdefault(symbol, {}).update({
                    "amount": live_after,
                    "exit_blocked_until": time.time() + 120,
                    "exit_blocked_reason": "EXIT_ACCEPTED_NO_WALLET_DELTA",
                })
                self._save_active_trades()
                _emit_trade_history("EXIT_PENDING", {
                    "source": "indodax_executor",
                    "venue": "indodax",
                    "symbol": symbol,
                    "pair": pair,
                    "side": "SELL",
                    "status": "PENDING",
                    "order_id": order_id,
                    "price_idr": price,
                    "amount_coin": amount,
                    "amount_idr": price * amount,
                    "reason": "EXIT_ACCEPTED_NO_WALLET_DELTA",
                    "trade_profile": trade.get("trade_profile", "STANDARD"),
                    "lifecycle": trade.get("lifecycle"),
                })
                return

            exit_amount = filled_amount if filled_amount > 0 else amount
            strategy = load_strategy()
            indo_strat = strategy.get("indodax", {}) if isinstance(strategy, dict) else {}
            fee_roundtrip_pct = float(indo_strat.get("fee_roundtrip_pct", 1.02) or 1.02)
            math_result = self._net_exit_result(trade, exit_amount, price, fee_roundtrip_pct)
            self.risk.update_pnl(math_result["net_pnl_idr"])
            if KiConfig.CANARY_LIVE_ENABLED and math_result["net_pnl_idr"] < 0:
                stats = self._load_canary_stats()
                stats["daily_loss_idr"] += abs(math_result["net_pnl_idr"])
                self._save_canary_stats(stats)
                logger.info(f"📉 CANARY STATS: Daily loss updated to Rp{stats['daily_loss_idr']:,.0f}")


            # ── §16.2 Order lifecycle reconcile ──
            if _ORDER_TRACKER_AVAILABLE:
                ot_order_id = trade.get("sovereign_order_id")
                if ot_order_id and not is_partial:
                    try:
                        sell_value_idr = price * exit_amount
                        _get_tracker().reconcile(
                            ot_order_id,
                            sell_value_idr=sell_value_idr,
                            fee_idr=math_result["fee_idr"],
                            gross_pnl_idr=math_result["gross_pnl_idr"],
                        )
                    except Exception as ot_err:
                        logger.warning(f"[Executor] OrderTracker reconcile failed for {symbol}: {ot_err}")

            logger.info(f"✅ EXIT FILLED: {symbol} via {reason} @ {price} amount={exit_amount:.8f}")
            if live_after > 1e-8:
                remaining_cost = max(
                    0.0,
                    float(trade.get("cost", 0.0) or 0.0) * (live_after / max(state_amount, 1e-9)),
                )
                self.active_trades.setdefault(symbol, {}).update({
                    "amount": live_after,
                    "cost": remaining_cost,
                    "price": float(trade.get("price", price) or price),
                    "partial_tp_done": bool(is_partial or trade.get("partial_tp_done", False)),
                    "last_exit_reason": reason,
                })
            else:
                self.active_trades.pop(symbol, None)
            self._save_active_trades()
            _emit_trade_history("SELL_FILLED", {
                "source": "indodax_executor",
                "venue": "indodax",
                "symbol": symbol,
                "pair": pair,
                "side": "SELL",
                "status": "FILLED",
                "order_id": trade.get("sovereign_order_id") or "",
                "exchange_order_id": res.get("return", {}).get("order_id") if isinstance(res.get("return"), dict) else "",
                "price_idr": price,
                "entry_price_idr": float(trade.get("price", price) or price),
                "exit_price_idr": price,
                "amount_coin": exit_amount,
                "amount_idr": math_result["exit_value_idr"],
                "fee_idr": math_result["fee_idr"],
                "gross_realized_pnl_idr": math_result["gross_pnl_idr"],
                "net_realized_pnl_idr": math_result["net_pnl_idr"],
                "realized_pnl_idr": math_result["net_pnl_idr"],
                "realized_pnl_pct": (math_result["net_pnl_idr"] / max(math_result["entry_cost_idr"], 1e-9)) * 100.0,
                "reason": reason,
                "partial": bool(live_after > 1e-8),
                "trade_profile": trade.get("trade_profile", "STANDARD"),
                "lifecycle": trade.get("lifecycle"),
            })
            if _ORDER_TRACKER_AVAILABLE:
                try:
                    log_execution_event("EXIT_FILLED", {
                        "symbol": symbol,
                        "reason": reason,
                        "price": price,
                        "amount": exit_amount,
                        "partial": is_partial,
                        "entry_price_idr": float(trade.get("price", price) or price),
                        "exit_price_idr": price,
                        "fee_idr": math_result["fee_idr"],
                        "gross_realized_pnl_idr": math_result["gross_pnl_idr"],
                        "net_realized_pnl_idr": math_result["net_pnl_idr"],
                    })
                except Exception:
                    pass
            self.report_to_batam(symbol, reason, f"Exit filled @ {price}")
        else:
            logger.error(f"❌ EXIT FAILED: {symbol} - {res.get('error')}")
            _emit_trade_history("EXIT_REJECTED", {
                "source": "indodax_executor",
                "venue": "indodax",
                "symbol": symbol,
                "pair": pair,
                "side": "SELL",
                "status": "REJECTED",
                "reason": str(res.get("error") or "exit_failed"),
                "price_idr": price,
                "amount_coin": amount,
                "amount_idr": price * amount,
                "trade_profile": trade.get("trade_profile", "STANDARD"),
                "lifecycle": trade.get("lifecycle"),
            })

    async def process_signal(self, signal):
        """Script-based signal processing using Council-defined parameters."""
        # 0. Check LLM Guards / Blocks
        if KiConfig.LLM_BLOCK_EXECUTOR:
            logger.error("🛑 LLM_BLOCK_EXECUTOR is True! All order placement and execution is strictly blocked.")
            return

        if not KiConfig.LLM_ALLOWED_TO_PLACE_ORDER and (signal.get("origin") == "LLM" or signal.get("type") == "LLM_DIRECT"):
            logger.error("🛑 LLM direct order placement is disabled (KiConfig.LLM_ALLOWED_TO_PLACE_ORDER is False). Bypassing signal.")
            return

        urgency = check_urgency()
        if urgency.get("flag") == "EMERGENCY_PAUSE": return

        # Check KILL SWITCH
        kill_switch_path = Path(ROOT_DIR) / "state" / "KILL_SWITCH"
        if kill_switch_path.exists():
            if signal.get("side", "BUY").upper() == "BUY":
                logger.error("🛑 KILL SWITCH ENGAGED! Blocking all new live buy entries.")
                return

        # Check Canary Mode constraints
        is_live = KiConfig.LIVE_TRADING_ENABLED or KiConfig.CANARY_LIVE_ENABLED
        if not is_live:
            symbol = signal.get("symbol", "UNKNOWN")
            logger.warning(f"🧪 PAPER MODE: live trading disabled; skipping live entry for {symbol}.")
            return

        symbol = signal.get("symbol", "UNKNOWN")
        side = signal.get("side", "BUY").upper()

        if KiConfig.CANARY_LIVE_ENABLED and side == "BUY":
            # 1. Exchange check
            if KiConfig.CANARY_EXCHANGE != "INDODAX":
                logger.warning(f"🛡️ CANARY CONSTRAINT: Exchange {KiConfig.CANARY_EXCHANGE} is not INDODAX. Blocking live entry.")
                return

            # 2. Council mandate verification
            if KiConfig.CANARY_REQUIRE_COUNCIL_APPROVAL and signal.get("type") != "COUNCIL_MANDATE":
                logger.warning(f"🛡️ CANARY CONSTRAINT REJECTED: Signal type '{signal.get('type')}' is not COUNCIL_MANDATE for {symbol}")
                return

            # 3. EV check (expected_net_pct > 0)
            strategy = load_strategy()
            indo_strat = strategy.get("indodax", {})
            fee_roundtrip_pct = float(indo_strat.get("fee_roundtrip_pct", 1.02))
            tp_pct = float(indo_strat.get("take_profit_pct", 1.5))
            expected_net_pct = tp_pct - fee_roundtrip_pct
            if KiConfig.CANARY_REQUIRE_POSITIVE_EV and expected_net_pct <= 0:
                logger.warning(f"🛡️ CANARY CONSTRAINT REJECTED: Expected net percent {expected_net_pct}% is not positive for {symbol}")
                return

            # 4. Single position limit check (active + reservations)
            max_open = KiConfig.CANARY_MAX_OPEN_POSITIONS
            current_active = len(self.active_trades) + len(self.reservations)
            if current_active >= max_open:
                logger.warning(f"🛡️ CANARY CONSTRAINT REJECTED: Single position limit reached ({current_active} active/reserved, max {max_open}).")
                return

            # 5. Daily trade limits and daily loss limits
            stats = self._load_canary_stats()
            max_daily_trades = KiConfig.CANARY_MAX_DAILY_TRADES
            if stats["trade_count"] >= max_daily_trades:
                logger.warning(f"🛡️ CANARY CONSTRAINT REJECTED: Daily trade limit reached ({stats['trade_count']}/{max_daily_trades}).")
                return

            from Core.risk_gate import _today_wib
            today = _today_wib()
            anchor = self.risk._load_equity_anchor()
            starting_equity = float(anchor.get("start_equity_idr", 0.0))
            if not anchor or anchor.get("date") != today:
                try:
                    starting_equity = await self.indodax.get_balance("idr")
                    if starting_equity > 0:
                        anchor = self.risk._save_equity_anchor(starting_equity)
                except Exception as e:
                    logger.error(f"Failed to fetch Indodax balance for guarded live check: {e}")
                    starting_equity = starting_equity or 184000.0

            effective_daily_loss_cap_idr = min(
                KiConfig.CANARY_MAX_DAILY_LOSS_IDR,
                starting_equity * (KiConfig.MAX_DAILY_LOSS_PERCENT / 100.0)
            )

            if stats["daily_loss_idr"] >= effective_daily_loss_cap_idr:
                logger.warning(
                    f"🛡️ CANARY CONSTRAINT REJECTED: Daily loss limit exceeded "
                    f"(Rp{stats['daily_loss_idr']:,.0f} >= Rp{effective_daily_loss_cap_idr:,.0f}). "
                    f"starting_equity: Rp{starting_equity:,.0f}"
                )
                return

        # Regular raw signal check when not under strict live guard or if RAW signals are allowed
        if not KiConfig.CANARY_LIVE_ENABLED and signal.get("type") != "COUNCIL_MANDATE" and os.getenv("KIBOT_EXECUTOR_ACCEPT_RAW_SIGNALS", "0").strip().lower() not in {"1", "true", "yes", "on"}:
            logger.debug(f"🛡️ Raw scanner signal ignored; waiting for Council mandate: {symbol}")
            return


        strategy = load_strategy()
        indo_strat = strategy.get("indodax", {})
        
        symbol = signal.get("symbol", "UNKNOWN")
        side = signal.get("side", "BUY")
        price = float(signal.get("price", 0))
        live_price, live_price_meta = await self._resolve_live_entry_price(symbol, price)
        if live_price > 0:
            price = live_price
            signal["price"] = price
            signal["live_entry_price_idr"] = price
            signal["live_entry_price_meta"] = live_price_meta
        confidence = signal.get("confidence", 0)
        change_pct = abs(signal.get("change_5m_pct", signal.get("change_pct", 0)))
        pump_stage = str(signal.get("pump_stage", "IGNITION") or "IGNITION").upper()
        trend_continuation = bool(signal.get("trend_continuation", False))
        pullback_reclaim = bool(signal.get("pullback_reclaim", False))
        late_reclaim = bool(signal.get("late_reclaim", False))
        range_break_reclaim = bool(signal.get("range_break_reclaim", False))
        support_bounce_reclaim = bool(signal.get("support_bounce_reclaim", False))
        pivot_reclaim = bool(signal.get("pivot_reclaim", False))
        mature_pump = bool(signal.get("mature_pump", False))
        learning_probe = bool(signal.get("learning_probe", False))

        # --- SCRIPT LOGIC (V3.2) ---
        max_exposure = float(indo_strat.get("max_exposure_idr", 0))
        max_slots = indo_strat.get("max_slots", 100)
        
        total_slots = 0
        async with self.lock:
            # Check total slots (Active + Reserved)
            total_slots = len(self.active_trades) + len(self.reservations)
            
            if max_exposure > 0 and total_slots >= max_slots and symbol not in self.active_trades and symbol not in self.reservations:
                logger.debug(f"🛡️ Slots full ({total_slots}/{max_slots}). Ignoring {symbol}.")
                return
            
            # Check if already in trade or being processed
            if symbol in self.active_trades or symbol in self.reservations:
                logger.debug(f"🛡️ Already active or reserved for {symbol}. Ignoring.")
                return
            
            # 1. RESERVE SLOT
            self.reservations[symbol] = time.time()
            logger.info(f"📝 RESERVED slot for {symbol} (Total: {total_slots + 1})")

        try:
            # 1. Get Balance
            current_balance = await self.indodax.get_balance("idr")
            if current_balance <= 0:
                logger.warning(f"🛡️ REJECTED: Zero balance, cannot trade {symbol}.")
                return
            total_equity_idr = max(
                float(signal.get("total_equity_idr") or signal.get("combined_equity_idr") or signal.get("equity_idr") or 0.0),
                float(current_balance or 0.0),
            )
            signal["total_equity_idr"] = total_equity_idr
            if side.lower() == "buy" and price >= total_equity_idr:
                logger.warning(
                    f"🛡️ REJECTED (Unit Price Rule): {symbol} 1 coin Rp{price:,.0f} >= total balance/equity Rp{total_equity_idr:,.0f}"
                )
                return
            
            # 2. Autonomous sizing
            if KiConfig.CANARY_LIVE_ENABLED:
                # Legacy compatibility path kept for tests / retired canary mode.
                remaining_slots = max(1, max_slots - len(self.active_trades))
                if max_exposure == 0:
                    budget = max(10_000.0, (current_balance / remaining_slots) * 0.98)
                else:
                    budget = max_exposure / max(1, max_slots)
                budget = min(budget, current_balance * 0.99)
                if learning_probe:
                    probe_cap = max(10_000.0, current_balance * 0.02)
                    budget = min(budget, probe_cap)
                max_budget = KiConfig.CANARY_MAX_TRADE_IDR
                if budget > max_budget:
                    logger.info(f"🛡️ CANARY CONSTRAINT: Clamping budget from Rp{budget:,.0f} to Rp{max_budget:,.0f}")
                    budget = max_budget
                sizing = {
                    "approved": True,
                    "reason": "legacy_canary_compat",
                    "size_idr": budget,
                    "capital_fraction": round(budget / max(current_balance, 1), 4),
                    "confidence": float(signal.get("confidence") or 0.0),
                    "max_loss_if_stop_hit_idr": round(budget * (float(signal.get("stop_loss_pct") or 1.5) / 100.0), 2),
                }
            else:
                liquidity_usd = float(signal.get("liquidity_usd") or signal.get("liquidity") or 0.0)
                slippage_pct = float(signal.get("slippage_pct") or signal.get("spread_pct") or 0.0)
                confidence = float(signal.get("confidence") or signal.get("score") or 0.0)
                ev_pct = float(signal.get("expected_net_pct") or signal.get("ev_pct") or signal.get("expected_value_pct") or 0.0)
                volatility_pct = float(signal.get("volatility_pct") or abs(signal.get("change_24h_pct") or signal.get("change_pct") or 0.0))
                stop_loss_pct = float(signal.get("stop_loss_pct") or indo_strat.get("hard_stop_pct") or indo_strat.get("stop_loss_pct") or 1.5)
                route_bucket_idr = float(signal.get("route_bucket_idr") or signal.get("budget_idr") or 0.0)
                if route_bucket_idr <= 0:
                    route_bucket_idr = current_balance
                sizing = self.sizing.size(
                    total_capital_idr=float(signal.get("total_equity_idr") or signal.get("combined_equity_idr") or current_balance or 0.0),
                    venue_capital_idr=float(current_balance or 0.0),
                    route_bucket_idr=float(route_bucket_idr),
                    available_balance_idr=float(current_balance or 0.0),
                    daily_risk_remaining_idr=float(signal.get("daily_risk_remaining_idr") or current_balance * (KiConfig.MAX_DAILY_LOSS_PERCENT / 100.0)),
                    liquidity_usd=liquidity_usd,
                    slippage_pct=slippage_pct,
                    confidence=confidence,
                    ev_pct=ev_pct,
                    volatility_pct=volatility_pct,
                    current_open_exposure_idr=float(signal.get("current_open_exposure_idr") or 0.0),
                    exit_available=bool(signal.get("exit_plan") or signal.get("exit_available", True)),
                    route="indodax",
                    reserve_locked=True,
                    hard_cap_idr=float(signal.get("hard_cap_idr") or 0.0),
                    liquidity_safe_size_idr=float(signal.get("liquidity_safe_size_idr") or 0.0),
                    momentum_score=float(signal.get("momentum_score") or signal.get("opportunity_score") or signal.get("pump_score") or 0.0),
                    exit_quality=str(signal.get("exit_quality") or ""),
                    trade_grade=str(signal.get("trade_grade") or signal.get("entry_quality") or ""),
                    stop_loss_pct=stop_loss_pct,
                    route_min_trade_idr=float(indo_strat.get("min_position_idr") or indo_strat.get("min_order_idr") or 10_000),
                )
                if not sizing.get("approved"):
                    logger.warning("🛡️ REJECTED (Sizing): %s for %s", sizing.get("reason"), symbol)
                    return
                budget = float(sizing.get("size_idr") or 0.0)
                if learning_probe:
                    budget = min(budget, max(10_000.0, current_balance * 0.02))
                signal["autonomous_sizing"] = sizing
            signal["budget_idr"] = budget


            fee_roundtrip_pct = float(indo_strat.get("fee_roundtrip_pct", 1.02))
            tp_pct = float(indo_strat.get("take_profit_pct", 1.5))
            expected_net_pct = tp_pct - fee_roundtrip_pct
            logger.info(
                f"📊 FEE CALC: TP={tp_pct:.2f}%, Fee={fee_roundtrip_pct:.2f}%, Net={expected_net_pct:.2f}%"
            )

            affordable, afford_reason = await self._can_afford(
                symbol,
                price,
                budget,
                indo_strat,
                total_equity_idr=total_equity_idr,
            )
            if not affordable:
                logger.warning(f"🛡️ REJECTED (Balance-Aware): {afford_reason} for {symbol}")
                return

            # Simulate the full buy-then-sell lifecycle against the live
            # orderbook before spending real money. This blocks the exact
            # failure mode that hurt the account: buying tiny/stuck books that
            # cannot be exited cleanly after fees and minimum-order rules.
            if _ORDER_TRACKER_AVAILABLE and side.lower() == "buy":
                try:
                    signal["max_spread_pct"] = float(indo_strat.get("max_spread_pct", 1.2) or 1.2)
                    if sizing.get("probe_mode") and float(signal.get("confidence") or 0.0) >= float(os.getenv("KIBOT_PROBE_MIN_CONFIDENCE", "0.78") or 0.78):
                        signal["max_spread_pct"] = max(
                            float(signal["max_spread_pct"]),
                            float(os.getenv("KIBOT_PROBE_MAX_SPREAD_PCT", "1.2") or 1.2),
                        )
                    simulation = await simulate_indodax_entry(
                        self.indodax,
                        symbol=symbol,
                        price=price,
                        budget_idr=budget,
                        signal=signal,
                        fee_roundtrip_pct=fee_roundtrip_pct,
                    )
                    log_pre_trade_simulation(simulation)
                    verdict = str(simulation.get("simulation_verdict") or "REJECT").upper()
                    if verdict == "REDUCE_SIZE":
                        reduced_budget = max(float(simulation.get("min_base_idr", 10_000) or 10_000), min(budget * 0.65, budget))
                        reduced_budget = min(reduced_budget, current_balance * 0.99)
                        retry = await simulate_indodax_entry(
                            self.indodax,
                            symbol=symbol,
                            price=price,
                            budget_idr=reduced_budget,
                            signal=signal,
                            fee_roundtrip_pct=fee_roundtrip_pct,
                        )
                        log_pre_trade_simulation({**retry, "retry_after_reduce": True})
                        if str(retry.get("simulation_verdict") or "REJECT").upper() == "PASS":
                            budget = reduced_budget
                            signal["budget_idr"] = budget
                            simulation = retry
                            logger.info(f"🧮 PRE-TRADE SIM: reduced {symbol} budget to Rp{budget:,.0f}")
                        else:
                            logger.warning(
                                f"🛡️ REJECTED (PreTradeSim): reduce retry failed for {symbol}: "
                                f"{retry.get('reasons')}"
                            )
                            return
                    elif verdict != "PASS":
                        logger.warning(
                            f"🛡️ REJECTED (PreTradeSim): {symbol} verdict={verdict} "
                            f"reasons={simulation.get('reasons')}"
                        )
                        return
                    signal["pre_trade_simulation"] = simulation
                except Exception as sim_err:
                    logger.warning(f"🛡️ REJECTED (PreTradeSim error): {symbol} {sim_err}")
                    return
            
            is_valid, reason = self.risk.validate_signal(signal, current_balance, total_slots)
            if not is_valid:
                logger.warning(f"🛡️ REJECTED: {reason} for {symbol}.")
                return

            # --- Indodax Microstructure Analyzer Hook ---
            try:
                from Core.Intelligence.indodax_microstructure import IndodaxMicrostructureAnalyzer
                analyzer = IndodaxMicrostructureAnalyzer()
                ob_data = await self.indodax.get_orderbook(symbol)
                analysis = analyzer.analyze_liquidity(ob_data, target_size_idr=budget)
                
                # Check net expected yield after fee and slippage adjustment
                gross_yield_pct = signal.get("expected_net_pct", signal.get("price", expected_net_pct))
                net_yield = analyzer.calculate_net_yield(gross_yield_pct, analysis.get("slippage_pct", 0.0))
                
                logger.info(
                    f"🔬 MICROSTRUCTURE [ {symbol} ]: Spread={analysis['spread_pct']:.3f}%, "
                    f"Slippage={analysis['slippage_pct']:.3f}%, NetYield={net_yield:.3f}%, "
                    f"Pass={analysis['pass_liquidity']}"
                )
                
                if not analysis["pass_liquidity"]:
                    logger.warning(f"🛡️ REJECTED (Microstructure): {analysis['reason']} for {symbol}")
                    return
                if net_yield <= 0.0:
                    logger.warning(f"🛡️ REJECTED (Microstructure Yield): Net expected yield {net_yield:.3f}% is negative.")
                    return
            except Exception as micro_err:
                logger.error(f"🛡️ REJECTED (Microstructure Exception): Fail-Closed triggered. Error: {micro_err}")
                return

            # 3. Minimum Spread Check (V3.2 Slippage Protection)
            try:
                spread_res = await self.indodax.get_orderbook(symbol)
                bids = spread_res.get("bids", [])
                asks = spread_res.get("asks", [])
                if bids and asks:
                    best_bid = float(bids[0][0])
                    best_ask = float(asks[0][0])
                    spread_pct = ((best_ask - best_bid) / best_bid) * 100
                    max_spread = float(indo_strat.get("max_spread_pct", 0.45))
                    if trend_continuation:
                        max_spread = max(max_spread, 0.50)
                    if pullback_reclaim:
                        max_spread = max(max_spread, 0.47)
                    if late_reclaim:
                        max_spread = max(max_spread, 0.48)
                    if range_break_reclaim:
                        max_spread = max(max_spread, 0.50)
                    if support_bounce_reclaim:
                        max_spread = max(max_spread, 0.50)
                    if pivot_reclaim:
                        max_spread = max(max_spread, 0.50)
                    if mature_pump:
                        max_spread = max(max_spread, 0.60)
                    if spread_pct > max_spread:
                        logger.warning(f"🛡️ REJECTED: Spread {spread_pct:.2f}% > limit {max_spread}% for {symbol}")
                        return
            except Exception as e:
                logger.error(f"Slippage check failed: {e}")

            # 4. Filter by Council Strategy
            # 4. Filter by Council Strategy (V3.1: "*" wildcard support)
            allowed = indo_strat.get("allowed_pairs", [])
            if "*" not in allowed and symbol not in allowed:
                logger.debug(f"🛡️ Symbol {symbol} not in allowed_pairs.")
                return

            min_confidence = float(indo_strat.get("min_confidence", 0.68))
            probe_confidence_floor = float(signal.get("probe_confidence_floor", max(0.60, min_confidence - 0.10)))
            required_confidence = probe_confidence_floor if learning_probe else min_confidence
            if trend_continuation:
                required_confidence = max(0.58 if not learning_probe else 0.55, required_confidence - 0.06)
            elif pullback_reclaim:
                required_confidence = max(0.57 if not learning_probe else 0.54, required_confidence - 0.05)
            elif late_reclaim:
                required_confidence = max(0.56 if not learning_probe else 0.53, required_confidence - 0.06)
            elif range_break_reclaim:
                required_confidence = max(0.57 if not learning_probe else 0.54, required_confidence - 0.05)
            elif support_bounce_reclaim:
                required_confidence = max(0.53 if not learning_probe else 0.50, required_confidence - 0.09)
            elif pivot_reclaim:
                required_confidence = max(0.50 if not learning_probe else 0.47, required_confidence - 0.10)
            elif mature_pump:
                required_confidence = max(0.56 if not learning_probe else 0.54, required_confidence - 0.08)

            if confidence < required_confidence:
                logger.debug(f"🛡️ Confidence {confidence} too low for Pump Hunter.")
                return
            
            # 4. Pump Intensity Check
            momentum_floor = float(indo_strat.get("buy_threshold_pct", 0.35))
            if trend_continuation:
                momentum_floor = max(0.20, momentum_floor - 0.15)
            elif pullback_reclaim:
                momentum_floor = max(0.25, momentum_floor - 0.10)
            elif late_reclaim:
                momentum_floor = max(0.18, momentum_floor - 0.17)
            elif range_break_reclaim:
                momentum_floor = max(0.20, momentum_floor - 0.12)
            elif support_bounce_reclaim:
                momentum_floor = max(0.16, momentum_floor - 0.16)
            elif pivot_reclaim:
                momentum_floor = max(0.14, momentum_floor - 0.18)
            elif mature_pump:
                momentum_floor = max(0.15, momentum_floor - 0.20)

            if change_pct < momentum_floor:
                logger.debug(f"🛡️ Momentum {change_pct}% too weak for Pump Hunter.")
                return

            # 2. Execution
            logger.info(f"⚡ SCRIPT EXECUTION: {side} {symbol} @ {price}")
            amount = self.risk.calculate_amount(symbol, price, budget)
            
            pair = symbol.lower().replace("/", "_")
            if "_" not in pair: pair = f"{pair}_idr"

            coin_symbol = pair.split("_")[0]
            coin_before = await self.indodax.get_balance(coin_symbol)
            res = await self.indodax.trade(
                pair=pair,
                type=side.lower(),
                price=price,
                amount_idr=budget if side.lower() == "buy" else None,
                amount_coin=amount if side.lower() == "sell" else None
            )

            if res.get("success") == 1:
                trade_data = res.get("return", {})
                filled_rp = float(trade_data.get("filled_rp") or 0.0)
                filled_coin = float(trade_data.get("filled_coin") or 0.0)
                actual_price = float(trade_data.get("price", price))
                await asyncio.sleep(1.5)
                coin_after = await self.indodax.get_balance(coin_symbol)
                acquired_coin = max(filled_coin, max(0.0, coin_after - coin_before))
                if acquired_coin <= 1e-8:
                    order_id = str(trade_data.get("order_id") or trade_data.get("orderId") or "")
                    pending_budget = filled_rp or budget
                    sovereign_order_id = None
                    if _ORDER_TRACKER_AVAILABLE:
                        try:
                            daily_ctx = signal.get("daily_context") if isinstance(signal.get("daily_context"), dict) else {}
                            try:
                                from Core.Intelligence.daily_context import get_daily_context
                                if not daily_ctx:
                                    daily_ctx = get_daily_context()
                            except Exception:
                                pass

                            capital_state_info = self.risk.get_capital_state(
                                current_balance, 0, len(self.active_trades)
                            )
                            if not ep:
                                ep = build_exit_plan(
                                    signal,
                                    daily_ctx,
                                    str(signal.get("capital_state") or capital_state_info.get("capital_state", "NORMAL")),
                                    signal.get("historian_profile") if isinstance(signal.get("historian_profile"), dict) else {},
                                )
                            pre_sim = signal.get("pre_trade_simulation") if isinstance(signal.get("pre_trade_simulation"), dict) else {}
                            if pre_sim and not pre_sim.get("partial_tp_feasible", True):
                                ep["partial_take_profit_fraction"] = 0.0
                                ep["partial_take_profit_disabled_reason"] = "minimum order would make partial TP unsellable"
                            mandate = {
                                "source": str(signal.get("type", "SIGNAL")),
                                "deadline_mode": daily_ctx.get("deadline_mode", signal.get("deadline_mode", "PATIENT")),
                                "budget_fraction": round(budget / max(current_balance, 1), 3),
                                "capital_state": signal.get("capital_state") or capital_state_info.get("capital_state", "NORMAL"),
                                "trade_grade": signal.get("trade_grade"),
                            }
                            tracker = _get_tracker()
                            sovereign_order_id = tracker.create(
                                symbol, "BUY", pending_budget, actual_price,
                                mandate, ep, signal
                            )
                            tracker.transition(
                                sovereign_order_id, "SUBMITTED",
                                exchange_order_id=order_id or None,
                                note="exchange accepted; wallet delta pending"
                            )
                            log_execution_event("ENTRY_PENDING", {
                                "symbol": symbol,
                                "price": actual_price,
                                "amount": 0.0,
                                "notional_idr": pending_budget,
                                "sovereign_order_id": sovereign_order_id,
                                "trade_grade": signal.get("trade_grade"),
                                "lifecycle": signal.get("lifecycle") or signal.get("pump_stage"),
                                "fallback_category": signal.get("fallback_category"),
                                "reason": "wallet delta pending",
                            })
                        except Exception as ot_err:
                            logger.warning(f"[Executor] OrderTracker pending create failed: {ot_err}")
                    pending_order_ref = order_id or str(sovereign_order_id or f"pending:{symbol}:{int(time.time())}")
                    logger.warning(
                        f"⏳ ENTRY PENDING: {symbol} order accepted but no filled coin yet. "
                        f"order_id={pending_order_ref or 'unknown'}"
                    )
                    _emit_trade_history("ENTRY_PENDING", {
                        "source": "indodax_executor",
                        "venue": "indodax",
                        "symbol": symbol,
                        "pair": pair,
                        "side": "BUY",
                        "status": "PENDING",
                        "order_id": pending_order_ref,
                        "price_idr": actual_price,
                        "amount_idr": pending_budget,
                        "trade_profile": "LEARNING_PROBE" if learning_probe else "STANDARD",
                        "lifecycle": signal.get("lifecycle") or signal.get("pump_stage"),
                        "reason": "no_filled_coin_yet",
                    })
                    self.active_trades[symbol] = {
                        "price": actual_price,
                        "amount": 0.0,
                        "high_price": actual_price,
                        "time": time.time(),
                        "cost": 0.0,
                        "trade_profile": "LEARNING_PROBE" if learning_probe else "STANDARD",
                        "learning_probe": learning_probe,
                        "sovereign_order_id": sovereign_order_id,
                        "entry_pending_order_id": pending_order_ref,
                        "entry_pending_exchange_order_id": order_id or "",
                        "entry_pending_budget_idr": pending_budget,
                        "entry_pending_price": actual_price,
                        "entry_pending_status": "OPEN",
                        "entry_pending_since": time.time(),
                        "entry_pending_reason": "wallet delta not yet visible",
                        "exit_plan": ep,
                        "pre_trade_simulation": signal.get("pre_trade_simulation", {}),
                        "trade_grade": signal.get("trade_grade"),
                        "lifecycle": signal.get("lifecycle") or signal.get("pump_stage"),
                        "fallback_category": signal.get("fallback_category"),
                        "category_policy": signal.get("category_policy", {}),
                        "unit_price_rule": {
                            "must_be_below_total_equity": True,
                            "price_idr": actual_price,
                            "total_equity_idr": signal.get("total_equity_idr"),
                        },
                        "deadline_mode": signal.get("deadline_mode"),
                        "capital_state": signal.get("capital_state"),
                    }
                    self._save_active_trades()
                    self.report_to_batam(symbol, "ENTRY_PENDING", f"Buy order pending @ {actual_price}")
                    return
                filled_coin = acquired_coin
                if filled_rp <= 0:
                    filled_rp = filled_coin * actual_price
                
                logger.info(f"✅ SUCCESS: {symbol} (Filled: Rp{filled_rp}, Coin: {filled_coin})")

                if KiConfig.CANARY_LIVE_ENABLED:
                    stats = self._load_canary_stats()
                    stats["trade_count"] += 1
                    self._save_canary_stats(stats)
                    logger.info(f"📈 CANARY STATS: Incrementing daily trade count to {stats['trade_count']}")


                # ── §16.2 Register with OrderTracker ──
                sovereign_order_id = None
                ep = signal.get("exit_plan") if isinstance(signal.get("exit_plan"), dict) else {}
                if _ORDER_TRACKER_AVAILABLE:
                    try:
                        daily_ctx = signal.get("daily_context") if isinstance(signal.get("daily_context"), dict) else {}
                        try:
                            from Core.Intelligence.daily_context import get_daily_context
                            if not daily_ctx:
                                daily_ctx = get_daily_context()
                        except Exception:
                            pass

                        capital_state_info = self.risk.get_capital_state(
                            current_balance, 0, len(self.active_trades)
                        )
                        if not ep:
                            ep = build_exit_plan(
                                signal,
                                daily_ctx,
                                str(signal.get("capital_state") or capital_state_info.get("capital_state", "NORMAL")),
                                signal.get("historian_profile") if isinstance(signal.get("historian_profile"), dict) else {},
                            )
                        pre_sim = signal.get("pre_trade_simulation") if isinstance(signal.get("pre_trade_simulation"), dict) else {}
                        if pre_sim and not pre_sim.get("partial_tp_feasible", True):
                            ep["partial_take_profit_fraction"] = 0.0
                            ep["partial_take_profit_disabled_reason"] = "minimum order would make partial TP unsellable"
                        mandate = {
                            "source": str(signal.get("type", "SIGNAL")),
                            "deadline_mode": daily_ctx.get("deadline_mode", signal.get("deadline_mode", "PATIENT")),
                            "budget_fraction": round(budget / max(current_balance, 1), 3),
                            "capital_state": signal.get("capital_state") or capital_state_info.get("capital_state", "NORMAL"),
                            "trade_grade": signal.get("trade_grade"),
                        }
                        tracker = _get_tracker()
                        sovereign_order_id = tracker.create(
                            symbol, "BUY", filled_rp, actual_price,
                            mandate, ep, signal
                        )
                        exchange_oid = str(
                            trade_data.get("order_id") or trade_data.get("orderId") or ""
                        )
                        tracker.transition(
                            sovereign_order_id, "SUBMITTED",
                            exchange_order_id=exchange_oid or None,
                            note="market order sent"
                        )
                        tracker.transition(
                            sovereign_order_id, "FILLED",
                            fill_price=actual_price,
                            coin_amount=filled_coin,
                            note="wallet delta confirmed"
                        )
                        logger.info(f"[Executor] OrderTracker: {sovereign_order_id} FILLED")
                    except Exception as ot_err:
                        logger.warning(f"[Executor] OrderTracker create failed: {ot_err}")

                self.active_trades[symbol] = {
                    "price": actual_price, 
                    "amount": filled_coin,
                    "high_price": actual_price,
                    "time": time.time(),
                    "cost": filled_rp,
                    "trade_profile": "LEARNING_PROBE" if learning_probe else "STANDARD",
                    "learning_probe": learning_probe,
                    "sovereign_order_id": sovereign_order_id,
                    "exit_plan": ep,
                    "pre_trade_simulation": signal.get("pre_trade_simulation", {}),
                    "trade_grade": signal.get("trade_grade"),
                    "lifecycle": signal.get("lifecycle") or signal.get("pump_stage"),
                    "fallback_category": signal.get("fallback_category"),
                    "category_policy": signal.get("category_policy", {}),
                    "unit_price_rule": {
                        "must_be_below_total_equity": True,
                        "price_idr": actual_price,
                        "total_equity_idr": signal.get("total_equity_idr"),
                    },
                    "deadline_mode": signal.get("deadline_mode"),
                    "capital_state": signal.get("capital_state"),
                }
                self._save_active_trades()
                if _ORDER_TRACKER_AVAILABLE:
                    try:
                        log_execution_event("OPEN", {
                            "symbol": symbol,
                            "price": actual_price,
                            "amount": filled_coin,
                            "notional_idr": filled_rp,
                            "sovereign_order_id": sovereign_order_id,
                            "trade_grade": signal.get("trade_grade"),
                            "lifecycle": signal.get("lifecycle") or signal.get("pump_stage"),
                            "fallback_category": signal.get("fallback_category"),
                        })
                    except Exception:
                        pass
                _emit_trade_history("ORDER_FILLED", {
                    "source": "indodax_executor",
                    "venue": "indodax",
                    "symbol": symbol,
                    "pair": pair,
                    "side": "BUY",
                    "status": "FILLED",
                    "order_id": trade_data.get("order_id") or trade_data.get("orderId") or "",
                    "sovereign_order_id": sovereign_order_id or "",
                    "exchange_order_id": trade_data.get("order_id") or trade_data.get("orderId") or "",
                    "price_idr": actual_price,
                    "amount_coin": filled_coin,
                    "amount_idr": filled_rp,
                    "trade_profile": "LEARNING_PROBE" if learning_probe else "STANDARD",
                    "lifecycle": signal.get("lifecycle") or signal.get("pump_stage"),
                    "reason": "wallet delta confirmed",
                })
                self.report_to_batam(
                    symbol,
                    "OPEN",
                    f"{'Probe ' if learning_probe else ''}Buy @ {actual_price}"
                )
            else:
                logger.error(f"❌ EXECUTION FAILED: {symbol} - {res.get('error')}")
                _emit_trade_history("ENTRY_REJECTED", {
                    "source": "indodax_executor",
                    "venue": "indodax",
                    "symbol": symbol,
                    "pair": pair,
                    "side": "BUY",
                    "status": "REJECTED",
                    "reason": str(res.get("error") or "entry_failed"),
                    "price_idr": price,
                    "amount_idr": budget,
                    "trade_profile": "LEARNING_PROBE" if learning_probe else "STANDARD",
                    "lifecycle": signal.get("lifecycle") or signal.get("pump_stage"),
                })

        finally:
            async with self.lock:
                self.reservations.pop(symbol, None)
                logger.info(f"🔓 RELEASED reservation for {symbol}")

    async def _can_afford(
        self,
        symbol: str,
        price: float,
        budget: float,
        indo_strat: Dict[str, Any],
        total_equity_idr: float | None = None,
    ) -> tuple[bool, str]:
        fee_rate = float(indo_strat.get("fee_roundtrip_pct", 1.02)) / 100.0
        effective_budget = budget * (1 - fee_rate)
        if price <= 0:
            return False, "INVALID_PRICE"

        if total_equity_idr is not None and price >= float(total_equity_idr or 0.0):
            return False, (
                f"UNIT_PRICE_ABOVE_TOTAL_BALANCE: Rp{price:,.0f} must be below "
                f"total balance/equity Rp{float(total_equity_idr or 0.0):,.0f}"
            )

        if price > effective_budget * 0.8:
            return False, f"COIN_TOO_EXPENSIVE: Rp{price:,.0f} > 80% budget Rp{effective_budget * 0.8:,.0f}"

        coin_amount = effective_budget / price
        if coin_amount < 1e-6:
            return False, f"DUST_ORDER: Amount terlalu kecil ({coin_amount:.8f} koin)"

        pair = symbol.lower().replace("/", "_")
        if "_" not in pair:
            pair = f"{pair}_idr"
        pair_info = await self.indodax.get_pair_info(pair)
        min_base = float(pair_info.get("trade_min_base_currency", 10_000) or 10_000)
        min_coin = float(pair_info.get("trade_min_traded_currency", 0) or 0)
        if budget < min_base:
            return False, f"BELOW_MIN_BASE_ORDER: budget Rp{budget:,.0f} < Rp{min_base:,.0f}"
        min_sellable_buffer_pct = float(indo_strat.get("min_sellable_buffer_pct", 2.0) or 2.0)
        min_sellable_amount = min_coin * (1.0 + min_sellable_buffer_pct / 100.0)
        if min_coin and coin_amount < min_sellable_amount:
            required_budget = (min_coin * price) / max(1e-9, 1 - fee_rate)
            return False, (
                f"BELOW_SELLABLE_MIN_AMOUNT: would buy {coin_amount:.8f}, "
                f"min sellable {min_coin:g} (+{min_sellable_buffer_pct:.1f}% buffer); "
                f"need budget ~Rp{required_budget:,.0f}"
            )

        tp_pct = float(indo_strat.get("take_profit_pct", 1.5))
        if tp_pct <= float(indo_strat.get("fee_roundtrip_pct", 1.02)):
            return False, f"FEE_EATS_PROFIT: TP {tp_pct:.2f}% <= fee {float(indo_strat.get('fee_roundtrip_pct', 1.02)):.2f}%"

        return True, "OK"

    def report_to_batam(self, symbol, status, msg):
        try:
            report = {
                "type": "EXECUTION_REPORT",
                "symbol": symbol,
                "status": status,
                "message": msg,
                "timestamp": datetime.now().isoformat()
            }
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(json.dumps(report).encode(), (self.batam_ip, REPORT_PORT))
        except: pass
    def handle_sigterm(self, signum, frame):
        logger.info("👋 IndodaxExecutor shutting down gracefully...")
        self._save_active_trades()
        self.running = False
        sys.exit(0)

class SignalProtocol(asyncio.DatagramProtocol):
    def __init__(self, executor):
        self.executor = executor

    def datagram_received(self, data, addr):
        from Core.Support.ki_utils import verify_signature
        secret = os.environ.get("KIBOT_SECRET")
        if not secret:
            logger.error("❌ CRITICAL: KIBOT_SECRET missing! Rejecting all signals.")
            return

        try:
            envelope = json.loads(data.decode())
            payload = envelope.get("data", {})
            signature = envelope.get("signature", "")
            
            if verify_signature(payload, signature, secret):
                # Check for list of signals (new format) or single signal
                signals = payload.get("signals", [])
                if not signals and "symbol" in payload:
                    signals = [payload]
                
                for s in signals:
                    asyncio.create_task(self.executor.process_signal(s))
            else:
                logger.warning(f"🛡️ REJECTED: Invalid HMAC signature from {addr}")
        except Exception as e:
            logger.error(f"UDP Parse/Verify Error: {e}")

if __name__ == "__main__":
    executor = IndodaxExecutor()
    
    # Register signal handlers
    signal.signal(signal.SIGTERM, executor.handle_sigterm)
    signal.signal(signal.SIGINT, executor.handle_sigterm)
    
    try:
        asyncio.run(executor.start())
    except KeyboardInterrupt:
        executor._save_active_trades()
        logger.info("🛑 Stopped.")
