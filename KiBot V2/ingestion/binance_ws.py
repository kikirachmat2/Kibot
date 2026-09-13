import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, Callable, Awaitable

from .base import BaseWebSocketClient
from .metrics import metrics_registry
from config import settings

logger = logging.getLogger("KiBotV2.BinanceWS")

def _safe_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    if val is None or val == "" or val == "NaN" or val == "null":
        return default
    try:
        f = float(val)
        import math
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default

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
            symbol = t.get("s", "")
            if not isinstance(symbol, str) or not symbol.endswith("USDT"):
                continue

            close_p = _safe_float(t.get("c"))
            if close_p is None or close_p <= 0:
                continue

            symbol_upper = symbol.upper().strip()
            metrics_registry.record_tick(symbol_upper, now_ts)
            if self.on_mini_ticker_cb:
                parsed = {
                    "symbol": symbol_upper,
                    "close": close_p,
                    "open": _safe_float(t.get("o"), default=close_p),
                    "high": _safe_float(t.get("h"), default=close_p),
                    "low": _safe_float(t.get("l"), default=close_p),
                    "volume": _safe_float(t.get("v"), default=0.0),
                    "quote_volume": _safe_float(t.get("q"), default=0.0),
                    "ts": now_ts,
                }
                await self.on_mini_ticker_cb(parsed)
