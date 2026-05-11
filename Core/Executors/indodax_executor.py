#!/usr/bin/env python3
# from Batam.Support.ki_vault import load_sovereign_env (Removed to allow dynamic loading below)
import asyncio
import json
import socket
import logging
import time
import os
import sys
from datetime import datetime
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

    async def start(self):
        print(f"🚀 {self.__class__.__name__} Starting...")
        asyncio.create_task(self.monitor_positions())
        self.running = True
        logger.info(f"🚀 Indodax Engine active on port {LISTEN_PORT}...")
        
        # Setup UDP Listener
        transport, protocol = await asyncio.get_event_loop().create_datagram_endpoint(
            lambda: SignalProtocol(self),
            local_addr=('0.0.0.0', LISTEN_PORT)
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
                urgency = check_urgency()

                if urgency.get("flag") == "EMERGENCY_PAUSE":
                    logger.warning(f"🚨 EMERGENCY PAUSE DETECTED: {urgency.get('reason')}")
                    await asyncio.sleep(5)
                    continue

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
                    if change >= indo_strat.get("take_profit_pct", 0.5):
                        logger.info(f"💰 TAKE PROFIT HIT: {symbol} @ {change:.2f}%")
                        await self.execute_exit(symbol, last_price, "TAKE_PROFIT")
                        continue

                    # 4. Midnight Oracle Exit
                    if strategy.get("global_mode") == "EXIT_ALL":
                        logger.info(f"🌑 MIDNIGHT DEADLINE: Liquidating {symbol} for Daily Report.")
                        await self.execute_exit(symbol, last_price, "MIDNIGHT_DEADLINE")

            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
            await asyncio.sleep(1)

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
            logger.info(f"✅ EXIT SUCCESS: {symbol} via {reason} @ {price}")
            self.active_trades.pop(symbol, None)
            self.report_to_batam(symbol, reason, f"Exit @ {price}")
        else:
            logger.error(f"❌ EXIT FAILED: {symbol} - {res.get('error')}")

    async def process_signal(self, signal):
        """Script-based signal processing using Council-defined parameters."""
        urgency = check_urgency()
        if urgency.get("flag") == "EMERGENCY_PAUSE": return

        strategy = load_strategy()
        indo_strat = strategy.get("indodax", {})
        
        symbol = signal.get("symbol", "UNKNOWN")
        side = signal.get("side", "BUY")
        price = float(signal.get("price", 0))
        confidence = signal.get("confidence", 0)
        change_pct = abs(signal.get("change_pct", 0))

        # --- SCRIPT LOGIC (V3.2) ---
        # 1. Max Slots Check
        if len(self.active_trades) >= indo_strat.get("max_slots", 4):
            logger.debug(f"🛡️ Slots full ({len(self.active_trades)}/4). Ignoring {symbol}.")
            return

        # 2. Price vs Balance Guard (Strict Sovereign Rule)
        # Price must be LESS THAN current total balance (FULL COIN RULE)
        # We fetch balance before buying
        current_balance = await self.indodax.get_balance("idr")
        if price >= current_balance:
            logger.warning(f"🛡️ REJECTED: Price {price} >= Balance {current_balance}. Too expensive for {symbol}.")
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
                max_spread = indo_strat.get("max_spread_pct", 0.5)
                if spread_pct > max_spread:
                    logger.warning(f"🛡️ REJECTED: Spread {spread_pct:.2f}% > limit {max_spread}% for {symbol}")
                    return
        except Exception as e:
            logger.error(f"Slippage check failed: {e}")
            # Fallback: continue if orderbook fetch fails but log it

        # 4. Filter by Council Strategy
        if symbol not in indo_strat.get("allowed_pairs", []):
            logger.debug(f"🛡️ Symbol {symbol} not in allowed_pairs.")
            return

        if confidence < indo_strat.get("min_confidence", 0.88):
            logger.debug(f"🛡️ Confidence {confidence} too low for Pump Hunter.")
            return
        
        # 4. Pump Intensity Check
        if change_pct < indo_strat.get("buy_threshold_pct", 0.8):
             logger.debug(f"🛡️ Momentum {change_pct}% too weak for Pump Hunter.")
             return

        # 2. Execution
        logger.info(f"⚡ SCRIPT EXECUTION: {side} {symbol} @ {price}")
        budget = float(indo_strat.get("max_exposure_idr", 25000) / 4) # Split budget
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
            logger.info(f"✅ SUCCESS: {symbol}")
            self.active_trades[symbol] = {
                "price": price, 
                "amount": amount,
                "high_price": price,
                "time": time.time()
            }

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
    # load_sovereign_env() # Already called in _load_vault() above
    executor = IndodaxExecutor()
    try:
        asyncio.run(executor.start())
    except KeyboardInterrupt:
        logger.info("🛑 Stopped.")
