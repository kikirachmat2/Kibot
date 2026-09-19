"""
KiBot V2 — Batam Node Auto-Discovery & Health Heartbeat.
Continuously probes the Batam research node (http://kibot-batam:5001/health) via Tailscale.
When discovered online, signals the KiBot pipeline to offload heavy analysis jobs.
Dispatches a single Telegram notification upon status transition to prevent alert spam.
"""
import asyncio
import logging
import os
import time
from typing import Any, Callable, Dict, Optional

import aiohttp
from config import settings

logger = logging.getLogger("KiBotV2.AutoDiscovery")

class BatamAutoDiscovery:
    def __init__(
        self,
        node_host: Optional[str] = None,
        node_port: int = 5001,
        check_interval_seconds: float = 300.0,
        request_timeout_seconds: float = 5.0,
        on_status_change_cb: Optional[Callable[[bool, Dict[str, Any]], None]] = None,
    ):
        self.node_host = node_host or os.getenv("KIBOT_BATAM_HOST", "kibot-batam")
        self.node_port = node_port
        self.check_interval_seconds = check_interval_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.on_status_change_cb = on_status_change_cb

        self.is_online = False
        self.last_check_ts: float = 0.0
        self.last_health_data: Optional[Dict[str, Any]] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

    @property
    def health_url(self) -> str:
        return f"http://{self.node_host}:{self.node_port}/health"

    async def check_health(self) -> bool:
        """Pings Batam research node health endpoint."""
        self.last_check_ts = time.time()
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.health_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.last_health_data = data
                        if not self.is_online:
                            self.is_online = True
                            logger.info(f"[AutoDiscovery] 🟢 Batam research node is ONLINE: {data.get('node')} (uptime: {data.get('uptime_s')}s)")
                            if self.on_status_change_cb:
                                self.on_status_change_cb(True, data)
                        return True
                    else:
                        logger.debug(f"[AutoDiscovery] Batam health check HTTP {resp.status}")
        except Exception as exc:
            logger.debug(f"[AutoDiscovery] Batam node unreachable ({self.node_host}:{self.node_port}): {exc}")

        if self.is_online:
            self.is_online = False
            logger.warning(f"[AutoDiscovery] 🔴 Batam research node went OFFLINE.")
            if self.on_status_change_cb:
                self.on_status_change_cb(False, {})
        else:
            logger.info(f"[AutoDiscovery] Batam not found ({self.node_host}:{self.node_port}), using internal fallback.")
        return False

    async def _discovery_loop(self) -> None:
        logger.info(f"[AutoDiscovery] Started Batam node monitor targeting {self.health_url} (interval={self.check_interval_seconds}s)")
        while self._running:
            await self.check_health()
            await asyncio.sleep(self.check_interval_seconds)

    def start(self) -> None:
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._discovery_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
