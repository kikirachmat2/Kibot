import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, Callable, Awaitable

from .base import BaseWebSocketClient
from .metrics import metrics_registry
from config import settings

logger = logging.getLogger("KiBotV2.BinanceWS")

class BinanceWebSocketClient(BaseWebSocketClient):
    """
    High-throughput, lightweight Binance WebSocket client.
    Streams !miniTicker@arr (24h mini-tickers every 1000ms) replacing the heavy 2.5MB REST polling.
    """
    def __init__(self, ws_base_url: Optional[str] = None):
        base_url = ws_base_url or settings.BINANCE_WS_URL
        stream_url = f"{base_url}/!miniTicker@arr"
        super().__init__(url=stream_url, name="BinanceWS")
        
        self.on_mini_ticker_cb: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
        self.on_message_cb = self._handle_message

    async def _handle_message(self, raw_msg: str) -> None:
        try:
            tickers = json.loads(raw_msg)
        except Exception:
            return

        if not isinstance(tickers, list):
            return

        now_ts = time.time()
        for t in tickers:
            if not isinstance(t, dict):
                continue
            symbol = t.get("s", "").upper()  # e.g. "BTCUSDT"
            if symbol.endswith("USDT"):
                metrics_registry.record_tick(symbol, now_ts)
                if self.on_mini_ticker_cb:
                    parsed = {
                        "symbol": symbol,
                        "close": float(t.get("c", 0.0)),
                        "open": float(t.get("o", 0.0)),
                        "high": float(t.get("h", 0.0)),
                        "low": float(t.get("l", 0.0)),
                        "volume": float(t.get("v", 0.0)),
                        "quote_volume": float(t.get("q", 0.0)),
                        "ts": now_ts,
                    }
                    await self.on_mini_ticker_cb(parsed)
