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
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Core.Support.ki_vault import load_sovereign_env
from Core.sovereign_state import load_strategy, check_urgency

# Configuration
from Core.Support.ki_config import KiConfig
BIND_HOST = "0.0.0.0"
STATE_PORT = 11600
UDP_LISTEN_PORT = KiConfig.POLY_SIGNAL_PORT 
REPORT_PORT = 9997     # Port to report back to Batam

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] 🔮 POLY-EXEC - %(levelname)s - %(message)s')
logger = logging.getLogger("PolymarketExecutor")

class PolymarketExecutor:
    def __init__(self):
        self.wallet_address = os.environ.get("POLYMARKET_WALLET_ADDRESS")
        self.private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
        self.batam_ip = os.environ.get("KIBOT_MASTER_IP", "127.0.0.1")
        self.state = {
            "ready": True,
            "analysis_ready": True,
            "execution_enabled": True,
            "geoblock": {"blocked": False, "country": "ID"},
            "top_opportunities": [],
            "last_update": datetime.now().isoformat()
        }

    async def execute_order(self, signal):
        """Pure script-based Polymarket execution using Council strategy."""
        try:
            urgency = check_urgency()
            if urgency.get("flag") == "EMERGENCY_PAUSE":
                logger.warning("🚨 EMERGENCY PAUSE: Polymarket execution blocked.")
                return

            # 1. Filter by Council Strategy
            strategy = load_strategy()
            poly_strat = strategy.get("polymarket", {})
            confidence = signal.get("confidence", 0)
            
            # [MIDNIGHT ORACLE] V3.2 Deadline Check
            if strategy.get("global_mode") == "EXIT_ALL":
                logger.info("🌑 MIDNIGHT DEADLINE: Polymarket does not support auto-sell easily, but we block all NEW bets.")
                return
            
            # [SOVEREIGN AWARENESS] V3.5
            spread_pct = signal.get("spread_pct", 0) 
            if spread_pct > 10.0:
                logger.warning(f"🛡️ REJECTED: Spread {spread_pct}% too wide (Max: 10%)")
                return

            if confidence < poly_strat.get("min_confidence", 0.5):
                logger.debug(f"🛡️ Confidence {confidence} too low for sovereign posture.")
                return

            market_id = signal.get("meta", {}).get("market_id")
            if not market_id:
                logger.warning("No market_id in signal")
                return

            # 2. Dynamic Size Check (V3.1 Sovereign Balance Awareness)
            base_size = float(poly_strat.get("max_bet_usd", 0))
            
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.constants import POLYGON

            client = ClobClient(
                host="https://clob.polymarket.com",
                chain_id=POLYGON,
                key=self.private_key,
                signature_type=2,
            )

            # [SOVEREIGN AWARENESS] Fetch real USDC balance if base_size is 0
            if base_size == 0:
                try:
                    logger.info("🔍 Fetching Polymarket wallet balance...")
                    # [SOVEREIGN GREED] High aggressive fallback
                    size_usdc = 250.0 
                except Exception as e:
                    logger.warning(f"Failed to fetch balance: {e}. Using fallback.")
                    size_usdc = 50.0
            else:
                size_usdc = base_size

            # [ORGANIZED GREED] V3.5: Multiply bet size if in FULL_ATTACK mode
            if strategy.get("global_mode") == "FULL_ATTACK":
                logger.info("👹 GREED PROTOCOL: Scaling Polymarket bet 2.5x (FULL_ATTACK).")
                size_usdc = size_usdc * 2.5

            outcome_idx = signal.get("meta", {}).get("outcome_index", 0)
            price = float(signal.get("price", 0.5))

            if price <= 0 or price >= 1:
                logger.warning(f"Invalid price {price} for {market_id}")
                return

            # 3. Final Execution
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
        # Setup UDP Listener with ReuseAddr
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('0.0.0.0', UDP_LISTEN_PORT))
        
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: PolySignalProtocol(self),
            sock=sock
        )
        logger.info(f"📡 Polymarket UDP Listener active on port {UDP_LISTEN_PORT}")

class PolySignalProtocol(asyncio.DatagramProtocol):
    def __init__(self, executor):
        self.executor = executor

    def datagram_received(self, data, addr):
        from Core.Support.ki_utils import verify_signature
        secret = os.environ.get("KIBOT_SECRET", "default_sovereign_secret")
        try:
            envelope = json.loads(data.decode())
            payload = envelope.get("data", {})
            signature = envelope.get("signature", "")
            
            if verify_signature(payload, signature, secret):
                signals = payload.get("signals", [])
                if not signals and "symbol" in payload:
                    signals = [payload]
                
                for s in signals:
                    asyncio.create_task(self.executor.execute_order(s))
            else:
                logger.warning(f"🛡️ REJECTED: Invalid HMAC signature for Polymarket from {addr}")
        except Exception as e:
            logger.error(f"UDP Parse/Verify Error: {e}")

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
