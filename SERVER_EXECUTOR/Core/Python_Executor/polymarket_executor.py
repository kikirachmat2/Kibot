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
        """Real Polymarket execution via CLOB API."""
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.constants import POLYGON

            market_id = signal.get("meta", {}).get("market_id")
            if not market_id:
                logger.warning("No market_id in signal")
                return

            client = ClobClient(
                host="https://clob.polymarket.com",
                chain_id=POLYGON,
                key=self.private_key,
                signature_type=2,  # POLY signature
            )

            outcome_idx = signal.get("meta", {}).get("outcome_index", 0)
            price       = float(signal.get("price", 0.5))
            size_usdc   = float(signal.get("meta", {}).get("size_usdc", 5.0))  # default $5 USDC

            if price <= 0 or price >= 1:
                logger.warning(f"Invalid price {price} for {market_id}")
                return

            order_args = OrderArgs(
                token_id=market_id,
                price=price,
                size=size_usdc,
                side="BUY",
                order_type=OrderType.GTC,
            )

            resp = client.create_and_post_order(order_args)
            logger.info(f"✅ Polymarket order placed: {resp}")
            self.report_to_batam(signal.get("symbol"), "SUCCESS", str(resp))

        except ImportError:
            logger.error("py-clob-client not installed: pip install py-clob-client")
            # Fallback ke dry-run
            self.report_to_batam(signal.get("symbol"), "DRY_RUN", "SDK not installed")
        except Exception as e:
            logger.error(f"Polymarket execution error: {e}")
            self.report_to_batam(signal.get("symbol"), "FAILED", str(e))

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
