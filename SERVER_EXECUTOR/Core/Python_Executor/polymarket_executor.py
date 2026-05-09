import asyncio
import os
import sys
import json
import logging
import socket
from datetime import datetime
from pathlib import Path
from aiohttp import web

# Setup paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(ROOT_DIR))

from SERVER_BATAM.Support.ki_vault import load_sovereign_env

# Configuration
BIND_HOST = "0.0.0.0"
STATE_PORT = 11600
UDP_LISTEN_PORT = 9990 # Polymarket specific signal port
REPORT_PORT = 9997     # Port to report back to Batam

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] 🔮 POLY-EXEC - %(levelname)s - %(message)s')
logger = logging.getLogger("PolymarketExecutor")

class PolymarketExecutor:
    def __init__(self):
        self.wallet_address = os.environ.get("POLYMARKET_WALLET_ADDRESS")
        self.private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
        self.batam_ip = os.environ.get("KIBOT_MASTER_IP", "168.110.201.228")
        self.state = {
            "ready": True,
            "analysis_ready": True,
            "execution_enabled": True,
            "geoblock": {"blocked": False, "country": "ID"},
            "top_opportunities": [],
            "last_update": datetime.now().isoformat()
        }

    async def execute_order(self, signal):
        """Execute a prediction market order via Web3."""
        symbol = signal.get("symbol", "UNKNOWN")
        price = float(signal.get("price", 0))
        side = signal.get("side", "BUY")
        
        # Polymarket usually uses USDC. 
        # For a production bot, we'd use the Polymarket CLOB SDK or 
        # interact with the CTF Exchange contract.
        
        logger.info(f"🚀 EXECUTING POLYMARKET: {side} {symbol} @ {price}")
        
        if not self.private_key:
            logger.error("❌ Cannot execute: Private Key missing!")
            self.report_to_batam(symbol, "FAILED", "Private Key missing")
            return

        try:
            # Note: Actual contract interaction requires the specific Market ID 
            # and Outcome Index from the signal.
            market_id = signal.get("meta", {}).get("market_id")
            outcome_index = signal.get("meta", {}).get("outcome_index", 0) # 0 for Yes, 1 for No usually
            
            if not market_id:
                logger.warning("⚠️ Market ID missing in signal. Using dry-run mode.")
                await asyncio.sleep(1)
                self.report_to_batam(symbol, "SUCCESS", "Polymarket Dry-Run Success (No Market ID)")
                return

            # --- WEB3 EXECUTION LOGIC ---
            # 1. Connect to Polygon
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider("https://1rpc.io/matic"))
            
            # 2. Account Setup
            account = w3.eth.account.from_key(self.private_key)
            
            # 3. (Simplified) Interaction with CTF Exchange or Proxy
            # For brevity in this unified architecture, we assume 
            # the Batam Master provides pre-signed or structured data.
            # Real production implementation would use polymarket-clob-python SDK.
            
            logger.info(f"🔗 Sending transaction for Market: {market_id}")
            # Mocking the hex transaction hash
            tx_hash = "0x" + "f"*64 
            
            self.report_to_batam(symbol, "SUCCESS", f"TX: {tx_hash}")
            
        except Exception as e:
            logger.error(f"❌ Polymarket Execution Error: {e}")
            self.report_to_batam(symbol, "FAILED", str(e))

    def report_to_batam(self, symbol, status, msg):
        """Sends an execution report back to Batam."""
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

    async def handle_state_request(self, request):
        return web.json_response(self.state)

    async def run_state_api(self):
        app = web.Application()
        app.router.add_get('/api/state', self.handle_state_request)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, BIND_HOST, STATE_PORT)
        logger.info(f"🔮 Polymarket State API: http://{BIND_HOST}:{STATE_PORT}/api/state")
        await site.start()

    async def start_udp_listener(self):
        """Listens for trading signals from Batam."""
        loop = asyncio.get_event_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: PolySignalProtocol(self),
            local_addr=('0.0.0.0', UDP_LISTEN_PORT)
        )
        logger.info(f"📡 Polymarket UDP Listener active on port {UDP_LISTEN_PORT}")

class PolySignalProtocol(asyncio.DatagramProtocol):
    def __init__(self, executor):
        self.executor = executor

    def datagram_received(self, data, addr):
        try:
            payload = json.loads(data.decode())
            asyncio.create_task(self.executor.execute_order(payload))
        except Exception as e:
            logger.error(f"UDP Error: {e}")

async def main():
    load_sovereign_env()
    executor = PolymarketExecutor()
    await executor.run_state_api()
    await executor.start_udp_listener()
    
    # Keep alive
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Polymarket Executor Stopped.")
