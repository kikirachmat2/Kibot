"""
KiBinance V2 — WebSocket Scanner | Port 8788 | Weight 0.35
v9.0 Sovereign Perfection: Real-time event streaming.
"""
import asyncio
import aiohttp
import json
import time
import os
from datetime import datetime, timezone
from ki_scanner_base import KiScannerBaseAsync, MANAGER_HOST, MANAGER_UDP_PORT

class KiBinanceScannerV2(KiScannerBaseAsync):
    WS_URL = "wss://stream.binance.com:9443/ws/!ticker@arr"

    def __init__(self):
        super().__init__("BINANCE", 8788)
        self.weights["BINANCE"] = 0.35  # Boosted weight for v9.0

    async def handle_async_logic(self):
        """Connects to Binance WebSocket and processes real-time ticker data."""
        session = await self._get_session()
        async with session.ws_connect(self.WS_URL) as ws:
            print(f"[BINANCE-V2] Connected to {self.WS_URL}")
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    await self._process_ws_data(data)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break

    async def _process_ws_data(self, ticker_list: list):
        """Processes the full ticker array from Binance."""
        if not isinstance(ticker_list, list):
            return

        for item in ticker_list:
            symbol = item.get("s", "")
            if not symbol.endswith("USDT"):
                continue
            
            base = symbol[:-4]
            try:
                price = float(item.get("c", 0))
                vol_usdt = float(item.get("q", 0))
                change_24h = float(item.get("P", 0))
                
                # V9.0 Added: Spread Analysis
                bid = float(item.get("b", 0))
                ask = float(item.get("a", 0))
                spread_pct = ((ask - bid) / ask * 100) if ask > 0 else 0
                
                # Detection Logic (inherited from base)
                sig = self.detect_signal(
                    base_symbol=base,
                    price=price,
                    vol_usdt=vol_usdt,
                    change_24h=change_24h
                )
                
                if sig:
                    # Enrich with V9.0 metrics
                    sig["spread_pct"] = round(spread_pct, 4)
                    sig["v9_enhanced"] = True
                    await self.send_signal_async(sig)
                    
            except Exception:
                continue

if __name__ == "__main__":
    scanner = KiBinanceScannerV2()
    asyncio.run(scanner.run_async())
