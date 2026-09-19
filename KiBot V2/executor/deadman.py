"""
KiBot V2 — Indodax Deadman Switch (Sovereign Safety Fallback).
Clean-room implementation of Indodax countdownCancelAll mechanism.

If the trading node crashes, loses power, or freezes unexpectedly,
Indodax automatically cancels all resting limit orders when the countdown timer expires.
Periodic heartbeat calls refresh the timer (default: every 5 minutes with a 15-minute countdown).
"""
import asyncio
import hashlib
import hmac
import logging
import time
from typing import Dict, List, Optional, Set
from urllib.parse import urlencode

import aiohttp
from config import settings

logger = logging.getLogger("KiBotV2.Deadman")

class IndodaxDeadmanSwitch:
    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        tapi_url: str = "https://indodax.com/tapi",
        default_timeout_seconds: int = 900,
        heartbeat_interval_seconds: int = 300,
    ):
        self.api_key = api_key or getattr(settings, "INDODAX_API_KEY", "")
        self.secret_key = secret_key or getattr(settings, "INDODAX_SECRET_KEY", "")
        self.tapi_url = tapi_url
        self.default_timeout_seconds = default_timeout_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.monitored_pairs: Set[str] = set()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_heartbeat_ts: float = 0.0

    def _sign(self, body: str) -> str:
        if not self.secret_key:
            return ""
        return hmac.new(self.secret_key.encode("utf-8"), body.encode("utf-8"), hashlib.sha512).hexdigest()

    def _build_headers(self, body: str) -> Dict[str, str]:
        return {
            "Key": self.api_key,
            "Sign": self._sign(body),
            "Content-Type": "application/x-www-form-urlencoded",
        }

    async def _send_countdown_cancel(self, pair: str, countdown_ms: int) -> bool:
        """Sends countdownCancelAll to Indodax TAPI endpoint."""
        if not self.api_key or not self.secret_key:
            logger.debug("[Deadman] Dry-run: Indodax API keys not configured. Mocking success.")
            return True

        ts = int(time.time() * 1000)
        params = {
            "method": "countdownCancelAll",
            "pair": pair,
            "countdownTime": str(countdown_ms),
            "timestamp": str(ts),
            "recvWindow": "5000",
        }
        body = urlencode(params)
        headers = self._build_headers(body)

        timeout = aiohttp.ClientTimeout(total=10.0)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.tapi_url, data=body, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        success = data.get("success") == 1
                        if success:
                            logger.info(f"[Deadman] ✅ Arm/Refresh countdownCancelAll for {pair}: {countdown_ms/1000:.0f}s")
                            return True
                        else:
                            logger.warning(f"[Deadman] ⚠️ Indodax returned error for {pair}: {data.get('error', 'unknown')}")
                            return False
                    else:
                        logger.warning(f"[Deadman] HTTP {resp.status} while refreshing deadman for {pair}")
                        return False
        except Exception as exc:
            logger.error(f"[Deadman] Connection error refreshing deadman for {pair}: {exc}")
            return False

    async def register_deadman(self, pair: str = "all", timeout_seconds: Optional[int] = None) -> bool:
        """Registers a pair and arms the countdownCancelAll timer on Indodax."""
        sec = timeout_seconds or self.default_timeout_seconds
        self.monitored_pairs.add(pair)
        res = await self._send_countdown_cancel(pair=pair, countdown_ms=sec * 1000)
        if res:
            self._last_heartbeat_ts = time.time()
        return res

    async def heartbeat(self) -> bool:
        """Refreshes countdownCancelAll on all currently monitored pairs."""
        if not self.monitored_pairs:
            # Default to 'all' if no specific pairs registered
            self.monitored_pairs.add("all")

        success_all = True
        for pair in list(self.monitored_pairs):
            res = await self._send_countdown_cancel(pair=pair, countdown_ms=self.default_timeout_seconds * 1000)
            if not res:
                success_all = False

        if success_all:
            self._last_heartbeat_ts = time.time()
        return success_all

    async def cancel_all_if_dead(self, pair: str = "all") -> bool:
        """Explicit safety fallback: triggers immediate order cancellation (countdownTime=0)."""
        logger.warning(f"[Deadman] 🛑 Triggering immediate cancellation fallback for pair: {pair}")
        return await self._send_countdown_cancel(pair=pair, countdown_ms=0)

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                await self.heartbeat()
            except Exception as e:
                logger.error(f"[Deadman] Error in periodic heartbeat loop: {e}", exc_info=True)
            await asyncio.sleep(self.heartbeat_interval_seconds)

    def start(self) -> None:
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._heartbeat_loop())
            logger.info(f"[Deadman] ⏱️ Indodax Deadman Switch periodic heartbeat started (interval={self.heartbeat_interval_seconds}s, timeout={self.default_timeout_seconds}s)")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[Deadman] Stopped Indodax Deadman Switch.")

deadman_switch = IndodaxDeadmanSwitch()

async def register_deadman(pair: str = "all", timeout_seconds: Optional[int] = None) -> bool:
    return await deadman_switch.register_deadman(pair=pair, timeout_seconds=timeout_seconds)

async def heartbeat() -> bool:
    return await deadman_switch.heartbeat()

async def cancel_all_if_dead(pair: str = "all") -> bool:
    return await deadman_switch.cancel_all_if_dead(pair=pair)

def start() -> None:
    deadman_switch.start()

async def stop() -> None:
    await deadman_switch.stop()

