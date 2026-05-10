#!/usr/bin/env python3
import asyncio
import json
import socket
import logging
import time
import os
import sys
from datetime import datetime
from pathlib import Path

# Setup paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(ROOT_DIR))

# Local Imports
from indodax_gateway import IndodaxGateway
from risk_gate import RiskGate
from Batam.Support.ki_vault import load_sovereign_env

# Logging Config
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] 🇮🇩 INDO-EXEC - %(levelname)s - %(message)s'
)
logger = logging.getLogger("IndodaxExecutor")

# Constants
LISTEN_PORT = 9999 # Received from Batam (Scanner)
REPORT_PORT = 9997 # Port to report back to Batam

class IndodaxExecutor:
    def __init__(self):
        self.indodax = IndodaxGateway()
        self.risk = RiskGate()
        self.active_trades = {} 
        self.running = False
        self.batam_ip = os.environ.get("KIBOT_MASTER_IP", "168.110.201.228")

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

    async def process_signal(self, signal):
        """Execute Indodax trade signals."""
        symbol = signal.get("symbol", "UNKNOWN")
        side = signal.get("side", "BUY")
        price = float(signal.get("price", 0))
        
        # Ignore Polymarket signals in this dedicated executor
        if symbol.startswith("POLY:"):
            return

        logger.info(f"🇮🇩 Processing: {side} {symbol} @ {price}")
        
        # 1. Fetch Fresh Balance
        balance_idr = await self.indodax.get_balance("idr")
        
        # 2. Risk Validation
        is_valid, reason = self.risk.validate_signal(
            signal, 
            balance_idr=balance_idr, 
            active_positions_count=len(self.active_trades)
        )

        if not is_valid:
            logger.warning(f"🛡️ REJECTED: {reason}")
            self.report_to_batam(symbol, "REJECTED", reason)
            return

        # 3. Execution
        budget = float(signal.get("budget_idr", 25000))
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
            order_id = res.get("return", {}).get("order_id")
            self.active_trades[symbol] = {"order_id": order_id, "price": price, "time": time.time()}
            self.report_to_batam(symbol, "SUCCESS", f"Order ID: {order_id}")
        else:
            logger.error(f"❌ FAILED: {res.get('error')}")
            self.report_to_batam(symbol, "FAILED", res.get("error"))

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

    async def monitor_positions(self):
        """Monitor open positions for auto TP/SL."""
        TP_PCT = 0.5  # Target Profit 0.5%
        SL_PCT = -0.3 # Stop Loss -0.3%
        while self.running:
            for symbol, trade in list(self.active_trades.items()):
                try:
                    pair = symbol.lower().replace("/", "_")
                    if "_" not in pair: pair = f"{pair}_idr"
                    ticker = await self.indodax.get_ticker(pair)
                    current = float(ticker.get("last", 0))
                    if not current: continue
                    entry = trade["price"]
                    change = (current - entry) / entry * 100
                    if change >= TP_PCT:
                        await self._execute_exit(symbol, current, "TP_HIT")
                    elif change <= SL_PCT:
                        await self._execute_exit(symbol, current, "SL_HIT")
                except Exception as e:
                    logger.debug(f"Monitor error {symbol}: {e}")
            await asyncio.sleep(5)

    async def _execute_exit(self, symbol, price, reason):
        pair = symbol.lower().replace("/", "_")
        if "_" not in pair: pair = f"{pair}_idr"
        trade = self.active_trades.get(symbol, {})
        amount = trade.get("amount", 0)
        if amount > 0:
            await self.indodax.trade(pair=pair, type="sell", 
                                   price=price, amount_coin=amount)
        self.active_trades.pop(symbol, None)
        self.report_to_batam(symbol, reason, f"Exit @ {price}")
        logger.info(f"{'✅ TP' if reason == 'TP_HIT' else '🔴 SL'}: {symbol} @ {price}")

class SignalProtocol(asyncio.DatagramProtocol):
    def __init__(self, executor):
        self.executor = executor

    def datagram_received(self, data, addr):
        try:
            payload = json.loads(data.decode())
            asyncio.create_task(self.executor.process_signal(payload))
        except Exception as e:
            logger.error(f"UDP Parse Error: {e}")

if __name__ == "__main__":
    load_sovereign_env()
    executor = IndodaxExecutor()
    try:
        asyncio.run(executor.start())
    except KeyboardInterrupt:
        logger.info("🛑 Stopped.")
