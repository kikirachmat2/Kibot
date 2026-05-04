"""
KiHunter — New Listing Scanner | Port 8799 | Weight 0.50 (Listing)
v9.0 Sovereign Perfection: Exploiting the listing pump.
"""
import asyncio
import aiohttp
import json
import time
from ki_scanner_base import KiScannerBaseAsync

class KiNewListingScanner(KiScannerBaseAsync):
    SOURCES = {
        "BINANCE": "https://api.binance.com/api/v3/exchangeInfo",
        "BYBIT": "https://api.bybit.com/v5/market/instruments-info?category=spot",
        "MEXC": "https://api.mexc.com/api/v3/defaultSymbols"
    }

    def __init__(self):
        super().__init__("LISTING_HUNTER", 8799)
        self._known_symbols = {ex: set() for ex in self.SOURCES}
        self.weights["LISTING_HUNTER"] = 0.50

    async def handle_async_logic(self):
        """Polls exchange metadata to detect new symbol additions."""
        print("[HUNTER] Monitoring for new listings...")
        while True:
            try:
                for exchange, url in self.SOURCES.items():
                    current_symbols = await self._fetch_symbols(exchange, url)
                    if not self._known_symbols[exchange]:
                        # First run: seed the list
                        self._known_symbols[exchange] = current_symbols
                        print(f"[HUNTER] Seeded {len(current_symbols)} symbols for {exchange}")
                        continue
                    
                    new_items = current_symbols - self._known_symbols[exchange]
                    for sym in new_items:
                        if not sym.endswith("USDT"): continue
                        print(f"🔥 [NEW LISTING] {sym} detected on {exchange}!")
                        await self._fire_listing_signal(exchange, sym)
                        self._known_symbols[exchange].add(sym)
                
                await asyncio.sleep(10) # 10s interval is safe
            except Exception as e:
                print(f"[HUNTER] Err: {e}")
                await asyncio.sleep(30)

    async def _fetch_symbols(self, exchange: str, url: str) -> set:
        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                data = await resp.json()
                if exchange == "BINANCE":
                    return {s["symbol"] for s in data["symbols"]}
                elif exchange == "BYBIT":
                    return {s["symbol"] for s in data["result"]["list"]}
                elif exchange == "MEXC":
                    return {s["symbol"] for s in data["data"]}
            return set()
        except:
            return set()

    async def _fire_listing_signal(self, exchange: str, symbol: str):
        base = symbol.replace("USDT", "")
        sig = {
            "exchange": exchange,
            "base_symbol": base,
            "pair_indodax": self.symbol_to_indodax(base),
            "type": "NEW_LISTING_EVENT",
            "detection_score": 0.99, # Hardcoded high score for new listings
            "weight": 0.50,
            "weighted_contrib": 0.495,
            "v9_enhanced": True,
            "note": "Immediate Entry Opportunity - New Exchange Listing"
        }
        if sig["pair_indodax"]:
            await self.send_signal_async(sig)

if __name__ == "__main__":
    scanner = KiNewListingScanner()
    asyncio.run(scanner.run_async())
