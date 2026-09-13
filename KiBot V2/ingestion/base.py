import asyncio
import logging
import random
import time
from enum import Enum
from typing import Optional, Callable, Awaitable
import websockets

logger = logging.getLogger("KiBotV2.WSBase")

class ConnectionState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"

class BaseWebSocketClient:
    def __init__(
        self,
        url: str,
        name: str = "WebSocketClient",
        min_backoff_s: float = 1.0,
        max_backoff_s: float = 30.0,
        heartbeat_interval_s: float = 5.0,
        heartbeat_timeout_s: float = 4.0,
    ):
        self.url = url
        self.name = name
        self.min_backoff_s = min_backoff_s
        self.max_backoff_s = max_backoff_s
        self.heartbeat_interval_s = heartbeat_interval_s
        self.heartbeat_timeout_s = heartbeat_timeout_s
        
        self.state: ConnectionState = ConnectionState.DISCONNECTED
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running: bool = False
        self._current_backoff_s: float = min_backoff_s
        self._last_heartbeat_ts: float = 0.0
        
        # Callbacks
        self.on_message_cb: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_reconnect_cb: Optional[Callable[[], Awaitable[None]]] = None

    async def start(self) -> None:
        self._running = True
        while self._running:
            try:
                self.state = ConnectionState.CONNECTING if self.state == ConnectionState.DISCONNECTED else ConnectionState.RECONNECTING
                logger.info(f"[{self.name}] Connecting to {self.url} (state={self.state})...")
                
                async with websockets.connect(
                    self.url,
                    ping_interval=None,  # We manage application-level or custom ping/pong actively
                    close_timeout=3.0,
                ) as ws:
                    self._ws = ws
                    self.state = ConnectionState.CONNECTED
                    self._current_backoff_s = self.min_backoff_s
                    self._last_heartbeat_ts = time.time()
                    logger.info(f"[{self.name}] ✅ Connected to {self.url}")
                    
                    # On successful reconnect, trigger snapshot resync if registered
                    if self.on_reconnect_cb:
                        try:
                            await self.on_reconnect_cb()
                        except Exception as sync_exc:
                            logger.error(f"[{self.name}] Error during reconnect callback: {sync_exc}")

                    # Spawn heartbeat monitor and message listener concurrently
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                    try:
                        async for message in ws:
                            self._last_heartbeat_ts = time.time()
                            if self.on_message_cb:
                                await self.on_message_cb(message)
                    finally:
                        heartbeat_task.cancel()
                        try:
                            await heartbeat_task
                        except asyncio.CancelledError:
                            pass
                            
            except (websockets.ConnectionClosed, OSError, asyncio.TimeoutError) as net_err:
                logger.warning(f"[{self.name}] Disconnected / Connection error: {net_err}")
            except Exception as unk_err:
                logger.error(f"[{self.name}] Unexpected error: {unk_err}")
                
            self.state = ConnectionState.DISCONNECTED
            self._ws = None
            if not self._running:
                break
                
            # Exponential backoff with jitter
            jitter = random.uniform(0.1, 0.5)
            sleep_time = min(self.max_backoff_s, self._current_backoff_s + jitter)
            logger.info(f"[{self.name}] Reconnecting in {sleep_time:.2f}s...")
            await asyncio.sleep(sleep_time)
            self._current_backoff_s = min(self.max_backoff_s, self._current_backoff_s * 2.0)

    async def _heartbeat_loop(self) -> None:
        """Actively checks for dead connections in < 5 seconds."""
        while self._running and self._ws:
            await asyncio.sleep(self.heartbeat_interval_s)
            now = time.time()
            # If no message or pong received within (interval + timeout), connection is dead
            if (now - self._last_heartbeat_ts) > (self.heartbeat_interval_s + self.heartbeat_timeout_s):
                logger.warning(f"[{self.name}] 🚨 Heartbeat timeout! Last active {now - self._last_heartbeat_ts:.2f}s ago. Force closing socket.")
                if self._ws:
                    await self._ws.close()
                break
            # Send ping
            try:
                if self._ws:
                    pong_waiter = await self._ws.ping()
                    await asyncio.wait_for(pong_waiter, timeout=self.heartbeat_timeout_s)
                    self._last_heartbeat_ts = time.time()
            except Exception as ping_exc:
                logger.warning(f"[{self.name}] Ping failure ({ping_exc}), dropping connection.")
                if self._ws:
                    await self._ws.close()
                break

    async def send_json(self, payload: dict) -> None:
        if self._ws and self.state == ConnectionState.CONNECTED:
            import json
            await self._ws.send(json.dumps(payload))
        else:
            raise ConnectionError(f"[{self.name}] Cannot send, client is {self.state}")

    async def stop(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()
        self.state = ConnectionState.DISCONNECTED
