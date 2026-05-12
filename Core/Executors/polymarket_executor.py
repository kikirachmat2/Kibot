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
        self.live_trading_enabled = KiConfig.LIVE_TRADING_ENABLED
        self.state = {
            "ready": True,
            "analysis_ready": True,
            "execution_enabled": self.live_trading_enabled,
            "live_trading_enabled": self.live_trading_enabled,
            "wallet_ready": bool(self.wallet_address and self.private_key),
            "geoblock": {"blocked": False, "country": "ID"},
            "top_opportunities": [],
            "last_update": datetime.now().isoformat()
        }
        logger.info(f"🚦 Polymarket live trading enabled: {self.live_trading_enabled}")

    async def _get_usdc_balance_polygon(self) -> float:
        try:
            from web3 import Web3
            rpc_url = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
            usdc_contract = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
            w3 = Web3(Web3.HTTPProvider(rpc_url))
            if not self.wallet_address or not w3.is_address(self.wallet_address):
                return 0.0
            abi = [{
                "inputs": [{"name": "account", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function"
            }]
            contract = w3.eth.contract(address=Web3.to_checksum_address(usdc_contract), abi=abi)
            balance_raw = contract.functions.balanceOf(Web3.to_checksum_address(self.wallet_address)).call()
            return balance_raw / 1_000_000
        except Exception as e:
            logger.debug(f"USDC balance fetch failed: {e}")
            return 0.0

    async def execute_order(self, signal):
        """Pure script-based Polymarket execution using Council strategy."""
        try:
            urgency = check_urgency()
            if urgency.get("flag") == "EMERGENCY_PAUSE":
                logger.warning("🚨 EMERGENCY PAUSE: Polymarket execution blocked.")
                return

            if not self.live_trading_enabled:
                logger.warning("🧪 PAPER MODE: live trading disabled; skipping Polymarket entry.")
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

            # 2. Dynamic Size Check (Balance-aware)
            base_size = float(poly_strat.get("max_bet_usd", 0))
            usdc_balance = await self._get_usdc_balance_polygon()
            if usdc_balance <= 0:
                logger.warning("🛡️ No USDC balance on Polygon. Skipping bet.")
                return
            
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.constants import POLYGON

            client = ClobClient(
                host="https://clob.polymarket.com",
                chain_id=POLYGON,
                key=self.private_key,
                signature_type=2,
            )

            if base_size == 0:
                size_usdc = usdc_balance * 0.20
            else:
                size_usdc = min(base_size, usdc_balance * 0.50)

            if size_usdc < 1.0:
                logger.warning(f"🛡️ Bet size terlalu kecil: ${size_usdc:.2f}")
                return

            if strategy.get("global_mode") == "FULL_ATTACK":
                logger.info("👹 GREED PROTOCOL: Scaling Polymarket bet 2x (FULL_ATTACK).")
                size_usdc = min(size_usdc * 2.0, usdc_balance * 0.40)

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
        self.state["last_update"] = datetime.now().isoformat()
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
