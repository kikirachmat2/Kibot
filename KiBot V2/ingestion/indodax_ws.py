import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, Callable, Awaitable, List
import aiohttp

from .base import BaseWebSocketClient
from .metrics import metrics_registry
from config import settings

logger = logging.getLogger("KiBotV2.IndodaxWS")

def _safe_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    if val is None or val == "" or val == "NaN" or val == "null" or val == "undefined":
        return default
    try:
        f = float(val)
        import math
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default

class IndodaxWebSocketClient(BaseWebSocketClient):
    def __init__(
        self,
        ws_url: Optional[str] = None,
        token: Optional[str] = None,
        rest_url: Optional[str] = None,
    ):
        url = ws_url or settings.INDODAX_WS_URL
        super().__init__(url=url, name="IndodaxWS")
        self.static_token = token or settings.INDODAX_WS_STATIC_TOKEN
        self.rest_url = rest_url or settings.INDODAX_REST_URL
        
        self.on_ticker_cb: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
        self.on_orderbook_cb: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None
        self.on_reconnect_cb = self._resync_snapshots
        self.on_message_cb = self._handle_message
        
        self._subscribed_orderbooks: set[str] = set()
        self._orderbook_cache: Dict[str, Dict[str, Any]] = {}
        self._req_id = 1
        self._http_session: Optional[aiohttp.ClientSession] = None

    async def _next_req_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _resync_snapshots(self) -> None:
        """Called automatically upon successful WebSocket connection/reconnection."""
        logger.info("[IndodaxWS] 🔄 Performing authentication and channel resync...")
        
        # 1. Authenticate with static token
        auth_id = await self._next_req_id()
        auth_msg = {
            "params": {"token": self.static_token},
            "id": auth_id,
        }
        await self.send_json(auth_msg)
        
        # 2. Subscribe to market:summary-24h
        sub_summary_id = await self._next_req_id()
        sub_summary_msg = {
            "method": 1,
            "params": {"channel": "market:summary-24h"},
            "id": sub_summary_id,
        }
        await self.send_json(sub_summary_msg)
        
        # 3. For any active orderbook subscriptions, fetch REST snapshot to avoid missing deltas
        if self._subscribed_orderbooks:
            logger.info(f"[IndodaxWS] Resyncing {len(self._subscribed_orderbooks)} orderbook snapshots via REST...")
            if not self._http_session or self._http_session.closed:
                self._http_session = aiohttp.ClientSession()
            for pair in list(self._subscribed_orderbooks):
                try:
                    await self._fetch_rest_depth_snapshot(pair)
                    # Resubscribe WS stream
                    sub_book_id = await self._next_req_id()
                    await self.send_json({
                        "method": 1,
                        "params": {"channel": f"market:order-book-{pair.lower().replace('/', '_')}"},
                        "id": sub_book_id,
                    })
                except Exception as e:
                    logger.error(f"[IndodaxWS] Failed to fetch REST depth for {pair}: {e}")

    async def fetch_orderbook(self, pair: str) -> Optional[Dict[str, Any]]:
        """Fetches fresh depth snapshot from Indodax REST API and updates cache."""
        formatted_pair = pair.lower().replace("/", "")
        url = f"{self.rest_url}/api/depth/{formatted_pair}"
        if not self._http_session or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        try:
            async with self._http_session.get(url, timeout=aiohttp.ClientTimeout(total=2.5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    book = {
                        "bids": data.get("buy", []),
                        "asks": data.get("sell", []),
                        "timestamp": time.time(),
                    }
                    norm_pair = pair.upper().replace("/", "").strip()
                    self._orderbook_cache[norm_pair] = book
                    metrics_registry.record_tick(pair)
                    if self.on_orderbook_cb:
                        await self.on_orderbook_cb(pair, {"type": "SNAPSHOT", **book})
                    return book
                else:
                    logger.warning(f"[IndodaxWS] Depth API returned status {resp.status} for {pair}")
                    return None
        except Exception as e:
            logger.error(f"[IndodaxWS] Failed to fetch REST depth for {pair}: {e}")
            return None

    async def get_orderbook(self, pair: str, max_age_s: float = 3.0) -> Optional[Dict[str, Any]]:
        """Returns cached orderbook if fresh, otherwise fetches live snapshot."""
        norm_pair = pair.upper().replace("/", "").strip()
        cached = self._orderbook_cache.get(norm_pair)
        if cached and (time.time() - cached.get("timestamp", 0) <= max_age_s):
            return cached
        return await self.fetch_orderbook(pair)

    async def _fetch_rest_depth_snapshot(self, pair: str) -> None:
        """Helper to fetch REST snapshot and notify callback."""
        await self.fetch_orderbook(pair)

    async def subscribe_orderbook(self, pair: str) -> None:
        """Dynamically subscribe to an orderbook channel for a high-interest candidate."""
        formatted_pair = pair.lower().replace("/", "_")
        self._subscribed_orderbooks.add(pair)
        if self.state == "CONNECTED":
            req_id = await self._next_req_id()
            await self.send_json({
                "method": 1,
                "params": {"channel": f"market:order-book-{formatted_pair}"},
                "id": req_id,
            })
            await self.fetch_orderbook(pair)

    async def _handle_message(self, raw_msg: str) -> None:
        try:
            msg = json.loads(raw_msg)
        except Exception:
            return

        if not isinstance(msg, dict):
            return

        result = msg.get("result")
        if not isinstance(result, dict):
            return

        channel = result.get("channel")
        if not isinstance(channel, str):
            return

        data_block = result.get("data", {})
        if not isinstance(data_block, dict):
            return

        # Handle 24h summary channel
        if "market:summary-24h" in channel:
            items = data_block.get("data", [])
            now_ts = time.time()
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, list) or len(item) < 5:
                        logger.warning(f"[IndodaxWS] ⚠️ Skipping malformed summary item (invalid structure): {item}")
                        continue

                    pair_raw = item[0]
                    if not pair_raw or not isinstance(pair_raw, str):
                        logger.warning(f"[IndodaxWS] ⚠️ Skipping item with invalid pair identifier: {pair_raw}")
                        continue

                    last_price = _safe_float(item[4])
                    if last_price is None or last_price <= 0:
                        logger.warning(f"[IndodaxWS] ⚠️ Skipping {pair_raw} due to invalid last_price: {item[4]}")
                        continue

                    high_24h = _safe_float(item[2], default=last_price)
                    low_24h = _safe_float(item[3], default=last_price)
                    vol_idr = _safe_float(item[5], default=0.0) if len(item) > 5 else 0.0

                    pair = pair_raw.upper().strip()
                    metrics_registry.record_tick(pair, now_ts)
                    if self.on_ticker_cb:
                        ticker_dict = {
                            "pair": pair,
                            "epoch": item[1] if len(item) > 1 else int(now_ts),
                            "last_price": last_price,
                            "high_24h": high_24h,
                            "low_24h": low_24h,
                            "volume_idr": vol_idr,
                        }
                        await self.on_ticker_cb(ticker_dict)
                            
        # Handle orderbook streaming channel
        elif "market:order-book-" in channel:
            pair = channel.replace("market:order-book-", "").upper()
            metrics_registry.record_tick(pair)
            if self.on_orderbook_cb:
                await self.on_orderbook_cb(pair, {"type": "DELTA", "data": data_block})

    async def stop(self) -> None:
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        await super().stop()
