"""
KiBit V2 — Bybit WebSocket Scanner | Port 8791 | Weight 0.30
v9.0 Sovereign Perfection: Real-time event streaming.
"""
import asyncio
import aiohttp
import json
import os
import time
from datetime import datetime, timezone
from ki_scanner_base import KiScannerBaseAsync

class KiBybitScannerV2(KiScannerBaseAsync):
    WS_URL = "wss://stream.bybit.com/v5/public/spot"
    REST_API = "https://api.bybit.com/v5/market/tickers?category=spot"

    def __init__(self):
        super().__init__("BYBIT", 8791)
        self.weights["BYBIT"] = 0.30

    async def handle_async_logic(self):
        """Initializes symbols and connects to Bybit WebSocket."""
        symbols = await self._fetch_all_usdt_symbols()
        if not symbols:
            print("[BYBIT-V2] No symbols found, retrying in 30s")
            await asyncio.sleep(30)
            return

        session = await self._get_session()
        async with session.ws_connect(self.WS_URL) as ws:
            # Subscribe in chunks of 10 to be safe
            for i in range(0, len(symbols), 10):
                chunk = symbols[i:i+10]
                sub_msg = {
                    "op": "subscribe",
                    "args": [f"tickers.{s}" for s in chunk]
                }
                await ws.send_str(json.dumps(sub_msg))
            
            print(f"[BYBIT-V2] Subscribed to {len(symbols)} tickers")

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if "data" in data and "topic" in data:
                        await self._process_ticker(data["data"])
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break

    async def _fetch_all_usdt_symbols(self) -> list:
        try:
            session = await self._get_session()
            async with session.get(self.REST_API) as resp:
                r = await resp.json()
                items = r.get("result", {}).get("list", [])
                return [i["symbol"] for i in items if i["symbol"].endswith("USDT")]
        except Exception as e:
            print(f"[BYBIT-V2] REST Fetch Err: {e}")
            return []

    async def _process_ticker(self, ticker: dict):
        symbol = ticker.get("symbol", "")
        if not symbol.endswith("USDT"):
            return
        
        base = symbol[:-4]
        try:
            price = float(ticker.get("lastPrice", 0))
            vol_b = float(ticker.get("volume24h", 0))
            # Bybit pct is in decimal (0.01 = 1%)
            change_24h = float(ticker.get("price24hPcnt", 0)) * 100
            
            # Bybit provides 1h prev price
            prev_1h = float(ticker.get("prevPrice1h", price) or price)
            change_1h = ((price - prev_1h) / prev_1h * 100) if prev_1h > 0 else 0
            
            sig = self.detect_signal(
                base_symbol=base,
                price=price,
                vol_usdt=vol_b * price,
                change_24h=change_24h,
                change_1h=change_1h
            )
            
            if sig:
                sig["v9_enhanced"] = True
                await self.send_signal_async(sig)
        except Exception:
            pass

if __name__ == "__main__":
    scanner = KiBybitScannerV2()
    asyncio.run(scanner.run_async())
