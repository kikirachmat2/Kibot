import json, time, asyncio, logging, aiohttp
from typing import List, Dict, Any

logger = logging.getLogger("UniversalScanner")

class UniversalLeadLagScanner:
    """
    Universal Lead-Lag Scanner (Async Engine)
    ========================================
    Monitors 18+ external sources to provide high-correlation signals.
    Detects when global markets (Binance, Upbit, etc.) lead local markets (Indodax).
    """
    def __init__(self):
        self.exchange = "UNIVERSAL_LEAD"
        self.sources = {
            "BINANCE": "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
            "UPBIT": "https://api.upbit.com/v1/ticker?markets=KRW-BTC",
            "BYBIT": "https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT",
            "OKX": "https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT",
            "GATE": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=BTC_USDT",
            "MEXC": "https://www.mexc.com/open/api/v2/market/ticker?symbol=BTC_USDT",
            "BYBIT_ETH": "https://api.bybit.com/v5/market/tickers?category=spot&symbol=ETHUSDT",
            "BINANCE_ETH": "https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT",
            "UPBIT_ETH": "https://api.upbit.com/v1/ticker?markets=KRW-ETH",
            "GATE_ETH": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=ETH_USDT",
            "BYBIT_SOL": "https://api.bybit.com/v5/market/tickers?category=spot&symbol=SOLUSDT",
            "BINANCE_SOL": "https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT",
            "UPBIT_SOL": "https://api.upbit.com/v1/ticker?markets=KRW-SOL",
            "GATE_SOL": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=SOL_USDT",
            "BYBIT_XRP": "https://api.bybit.com/v5/market/tickers?category=spot&symbol=XRPUSDT",
            "BINANCE_XRP": "https://api.binance.com/api/v3/ticker/price?symbol=XRPUSDT",
            "UPBIT_XRP": "https://api.upbit.com/v1/ticker?markets=KRW-XRP",
            "GATE_XRP": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=XRP_USDT",
        }
        self.last_prices = {}
        self.pending_signals = []
        self._lock = asyncio.Lock()
        
    async def _fetch_one(self, session, name, url):
        try:
            async with session.get(url, timeout=1.5) as response:
                if response.status == 200:
                    data = await response.json()
                    price = 0.0
                    if "binance" in url: price = float(data.get("price", 0))
                    elif "upbit" in url: 
                        from Core.Support.ki_config import KiConfig
                        rate = getattr(KiConfig, "KRW_USD_RATE", 1350.0)
                        price = float(data[0].get("trade_price", 0)) / rate
                    elif "bybit" in url: price = float(data.get("result", {}).get("list", [{}])[0].get("lastPrice", 0))
                    elif "okx" in url: price = float(data.get("data", [{}])[0].get("last", 0))
                    elif "gate" in url: price = float(data[0].get("last", 0))
                    elif "mexc" in url: price = float(data.get("last", 0))
                    
                    if price > 0:
                        await self._process_single_result(name, price)
                    return name, price
        except Exception: pass
        return name, 0.0

    async def _process_single_result(self, name, price):
        """Processes a single price result immediately for low latency."""
        now = time.time()
        async with self._lock:
            if name in self.last_prices:
                old_p = self.last_prices[name]
                change = (price - old_p) / old_p * 100 if old_p else 0
                if abs(change) >= 0.08: # Slightly tighter threshold for v2
                    signal = {
                        "type": "GLOBAL_LEAD",
                        "symbol": name.split("_")[0],
                        "source": name,
                        "price": round(price, 4),
                        "change_pct": round(change, 3),
                        "verdict": "BULLISH" if change > 0 else "BEARISH",
                        "confidence": abs(change) * 5,
                        "ts": int(now * 1000),
                        "priority": "HIGH" if "BINANCE" in name or "UPBIT" in name else "NORMAL"
                    }
                    self.pending_signals.append(signal)
            self.last_prices[name] = price

    async def _fetch_all(self):
        async with aiohttp.ClientSession() as session:
            # We don't await the gather if we want true stream, but here we still 
            # trigger all, they just process independently via _process_single_result
            tasks = [self._fetch_one(session, name, url) for name, url in self.sources.items()]
            await asyncio.gather(*tasks)

    def collect_signals(self) -> Dict[str, Any]:
        """Returns signals that have been detected since the last call."""
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                future = asyncio.run_coroutine_threadsafe(self._fetch_all(), loop)
                future.result(timeout=2)
            else:
                asyncio.run(asyncio.wait_for(self._fetch_all(), timeout=2))
        except Exception as e:
            logger.debug(f"Universal scanner fetch partial/timeout: {e}")
        
        signals = list(self.pending_signals)
        self.pending_signals.clear()
        return {"signals": signals}

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    scanner = UniversalLeadLagScanner()
    logger.info("🚀 Starting Universal Lead-Lag Scanner...")
    
    async def main():
        while True:
            signals = scanner.collect_signals()
            if signals.get("signals"):
                logger.info(f"Detected Signals: {signals['signals']}")
            await asyncio.sleep(2)
            
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Scanner stopped.")
