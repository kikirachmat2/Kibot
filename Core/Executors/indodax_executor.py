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
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
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

from Core.Support.ki_config import KiConfig
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
        sock.bind(('0.0.0.0', LISTEN_PORT))
        
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
                strategy = load_strategy()
                indo_strat = strategy.get("indodax", {})
                daily_state = strategy.get("daily_state", {}) if isinstance(strategy.get("daily_state"), dict) else {}
                green_hold_mode = str(daily_state.get("color", "")).upper() == "GREEN" and bool(daily_state.get("hold_winners", False))
                green_hold_multiplier = float(
                    indo_strat.get("green_hold_tp_multiplier", daily_state.get("take_profit_multiplier", 1.0)) or 1.0
                )
                urgency = check_urgency()

                if urgency.get("flag") == "EMERGENCY_PAUSE":
                    logger.warning(f"🚨 EMERGENCY PAUSE DETECTED: {urgency.get('reason')}")
                else:
                    for symbol, data in list(self.active_trades.items()):
                        current_price_data = await self.indodax.get_ticker(symbol.lower().replace("/", "_"))
                        last_price = float(current_price_data.get("last", 0))
                        entry_price = data.get("price")
                        
                        if last_price <= 0: continue

                        change = (last_price - entry_price) / entry_price * 100
                        
                        # 1. Hard Stop Loss
                        if change <= -indo_strat.get("hard_stop_pct", 1.5):
                            logger.warning(f"🛑 HARD STOP TRIGGERED: {symbol} @ {change:.2f}%")
                            await self.execute_exit(symbol, last_price, "HARD_STOP")
                            continue
                        
                        # 2. Trailing Stop
                        high_price = data.get("high_price", entry_price)
                        if last_price > high_price:
                            self.active_trades[symbol]["high_price"] = last_price
                            high_price = last_price
                        
                        from_high = (high_price - last_price) / high_price * 100
                        if from_high >= indo_strat.get("trailing_stop_pct", 0.25) and change > 0:
                            logger.info(f"📉 TRAILING STOP TRIGGERED: {symbol} @ {from_high:.2f}% from high")
                            await self.execute_exit(symbol, last_price, "TRAILING_STOP")
                            continue

                        # 3. Dynamic Take Profit (V3.2 fallback)
                        base_take_profit_pct = float(indo_strat.get("take_profit_pct", 0.5))
                        effective_take_profit_pct = base_take_profit_pct
                        if green_hold_mode:
                            effective_take_profit_pct = base_take_profit_pct * max(1.0, green_hold_multiplier)
                            if change >= base_take_profit_pct and change < effective_take_profit_pct:
                                logger.debug(
                                    f"🟢 GREEN HOLD: {symbol} holding profit @ {change:.2f}% "
                                    f"(TP {base_take_profit_pct:.2f}% -> {effective_take_profit_pct:.2f}%)"
                                )

                        if change >= effective_take_profit_pct:
                            logger.info(f"💰 TAKE PROFIT HIT: {symbol} @ {change:.2f}%")
                            await self.execute_exit(symbol, last_price, "TAKE_PROFIT")
                            continue

                        # 4. Midnight Oracle Exit
                        if strategy.get("global_mode") == "EXIT_ALL":
                            logger.info(f"🌑 MIDNIGHT DEADLINE: Liquidating {symbol} for Daily Report.")
                            await self.execute_exit(symbol, last_price, "MIDNIGHT_DEADLINE")

            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
            finally:
                await asyncio.sleep(5)

    async def execute_exit(self, symbol, price, reason):
        """Unified exit logic with reporting to Batam."""
        pair = symbol.lower().replace("/", "_")
        if "_" not in pair: pair = f"{pair}_idr"
        
        trade = self.active_trades.get(symbol, {})
        amount = trade.get("amount", 0)
        
        if amount <= 0:
            logger.warning(f"⚠️ EXIT SKIPPED: No amount for {symbol}")
            return

        res = await self.indodax.trade(pair=pair, type="sell", price=price, amount_coin=amount)
        
        if res.get("success") == 1:
            # Calculate PnL for RiskGate
            pnl_amount = (price - trade.get("price", 0)) * amount
            self.risk.update_pnl(pnl_amount)
            
            logger.info(f"✅ EXIT SUCCESS: {symbol} via {reason} @ {price}")
            self.active_trades.pop(symbol, None)
            self._save_active_trades()
            self.report_to_batam(symbol, reason, f"Exit @ {price}")
        else:
            logger.error(f"❌ EXIT FAILED: {symbol} - {res.get('error')}")

    async def process_signal(self, signal):
        """Script-based signal processing using Council-defined parameters."""
        urgency = check_urgency()
        if urgency.get("flag") == "EMERGENCY_PAUSE": return

        if not KiConfig.LIVE_TRADING_ENABLED:
            symbol = signal.get("symbol", "UNKNOWN")
            logger.warning(f"🧪 PAPER MODE: live trading disabled; skipping live entry for {symbol}.")
            return

        strategy = load_strategy()
        indo_strat = strategy.get("indodax", {})
        
        symbol = signal.get("symbol", "UNKNOWN")
        side = signal.get("side", "BUY")
        price = float(signal.get("price", 0))
        confidence = signal.get("confidence", 0)
        change_pct = abs(signal.get("change_5m_pct", signal.get("change_pct", 0)))
        pump_stage = str(signal.get("pump_stage", "IGNITION") or "IGNITION").upper()
        trend_continuation = bool(signal.get("trend_continuation", False))
        pullback_reclaim = bool(signal.get("pullback_reclaim", False))
        late_reclaim = bool(signal.get("late_reclaim", False))
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
            
            # 2. Risk Validation
            # 2. Dynamic Budget Allocation (V3.1 Sovereign Balance Awareness)
            remaining_slots = max(1, max_slots - len(self.active_trades))
            
            if max_exposure == 0:
                # [SOVEREIGN GREED] Use all available balance divided by remaining slots
                budget = max(10_000.0, (current_balance / remaining_slots) * 0.98)
            else:
                budget = max_exposure / max(1, max_slots)

            # Ensure it doesn't exceed current balance and meets minimums
            budget = min(budget, current_balance * 0.99)

            if learning_probe:
                probe_cap = max(10_000.0, current_balance * 0.02)
                budget = min(budget, probe_cap)
                logger.info(
                    f"🧪 LEARNING PROBE: budget capped to Rp{budget:,.0f} "
                    f"(cap Rp{probe_cap:,.0f}) for {symbol}"
                )

            signal["budget_idr"] = budget

            fee_roundtrip_pct = float(indo_strat.get("fee_roundtrip_pct", 1.02))
            tp_pct = float(indo_strat.get("take_profit_pct", 1.5))
            expected_net_pct = tp_pct - fee_roundtrip_pct
            logger.info(
                f"📊 FEE CALC: TP={tp_pct:.2f}%, Fee={fee_roundtrip_pct:.2f}%, Net={expected_net_pct:.2f}%"
            )

            affordable, afford_reason = self._can_afford(symbol, price, budget, indo_strat)
            if not affordable:
                logger.warning(f"🛡️ REJECTED (Balance-Aware): {afford_reason} for {symbol}")
                return
            
            is_valid, reason = self.risk.validate_signal(signal, current_balance, total_slots)
            if not is_valid:
                logger.warning(f"🛡️ REJECTED: {reason} for {symbol}.")
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

            res = await self.indodax.trade(
                pair=pair,
                type=side.lower(),
                price=price,
                amount_idr=budget if side.lower() == "buy" else None,
                amount_coin=amount if side.lower() == "sell" else None
            )

            if res.get("success") == 1:
                trade_data = res.get("return", {})
                filled_rp = float(trade_data.get("filled_rp", budget))
                filled_coin = float(trade_data.get("filled_coin", amount))
                actual_price = float(trade_data.get("price", price))
                
                logger.info(f"✅ SUCCESS: {symbol} (Filled: Rp{filled_rp}, Coin: {filled_coin})")
                self.active_trades[symbol] = {
                    "price": actual_price, 
                    "amount": filled_coin,
                    "high_price": actual_price,
                    "time": time.time(),
                    "cost": filled_rp,
                    "trade_profile": "LEARNING_PROBE" if learning_probe else "STANDARD",
                    "learning_probe": learning_probe
                }
                self._save_active_trades()
                self.report_to_batam(
                    symbol,
                    "OPEN",
                    f"{'Probe ' if learning_probe else ''}Buy @ {actual_price}"
                )
            else:
                logger.error(f"❌ EXECUTION FAILED: {symbol} - {res.get('error')}")

        finally:
            async with self.lock:
                self.reservations.pop(symbol, None)
                logger.info(f"🔓 RELEASED reservation for {symbol}")

    def _can_afford(self, symbol: str, price: float, budget: float, indo_strat: Dict[str, Any]) -> tuple[bool, str]:
        fee_rate = float(indo_strat.get("fee_roundtrip_pct", 1.02)) / 100.0
        effective_budget = budget * (1 - fee_rate)
        if price <= 0:
            return False, "INVALID_PRICE"

        if price > effective_budget * 0.8:
            return False, f"COIN_TOO_EXPENSIVE: Rp{price:,.0f} > 80% budget Rp{effective_budget * 0.8:,.0f}"

        coin_amount = effective_budget / price
        if coin_amount < 1e-6:
            return False, f"DUST_ORDER: Amount terlalu kecil ({coin_amount:.8f} koin)"

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
