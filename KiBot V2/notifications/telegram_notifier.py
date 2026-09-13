"""
Async non-blocking Telegram alert notifier for KiBot V2.
Ported and streamlined from V1 SovereignNotifier & TelegramExceptionNotifier.
Guaranteed never to block the trading hot-path.
"""
import asyncio
import hashlib
import json
import logging
import os
import time
from typing import Optional, Dict, Any

import aiohttp
from config import settings

logger = logging.getLogger("KiBotV2.Notifications")

class TelegramNotifier:
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        global_min_interval_s: float = 3.0,
        event_cooldown_s: float = 300.0,
    ):
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or settings.TELEGRAM_CHAT_ID
        self.global_min_interval_s = global_min_interval_s
        self.event_cooldown_s = event_cooldown_s
        
        self._last_sent_time: float = 0.0
        self._event_last_sent: Dict[str, float] = {}
        self._event_payload_hashes: Dict[str, str] = {}
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._warned_missing_credentials = False
        
        if not self.bot_token or not self.chat_id:
            logger.warning("[TelegramNotifier] ⚠️ Telegram credentials missing (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set). Notifications will be safely skipped.")
            self._warned_missing_credentials = True
        else:
            logger.info("[TelegramNotifier] ✅ Initialized with configured Telegram chat.")

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def _hash_payload(self, event_type: str, message: str) -> str:
        raw = f"{event_type}:{message}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _should_throttle(self, event_type: str, payload_hash: str, force: bool) -> bool:
        if force:
            return False
        now = time.time()
        # Global burst limit (minimum interval between any two telegram calls)
        if now - self._last_sent_time < self.global_min_interval_s:
            return True
        # Per-event deduplication & cooldown
        last_event_time = self._event_last_sent.get(event_type, 0.0)
        last_hash = self._event_payload_hashes.get(event_type, "")
        if last_hash == payload_hash and (now - last_event_time < self.event_cooldown_s):
            return True
        return False

    async def send_alert(
        self,
        event_type: str,
        title: str,
        message: str,
        severity: str = "HIGH",
        details: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> bool:
        """
        Asynchronously sends formatted alert to Telegram.
        Never raises uncaught exceptions.
        """
        if not self.is_configured:
            if not self._warned_missing_credentials:
                logger.warning("[TelegramNotifier] Skipping alert (Telegram credentials not configured).")
                self._warned_missing_credentials = True
            return False

        payload_hash = self._hash_payload(event_type, message)
        if self._should_throttle(event_type, payload_hash, force):
            logger.debug(f"[TelegramNotifier] Throttled duplicate alert: {event_type}")
            return False

        severity_icons = {
            "CRITICAL": "🚨🚨🚨",
            "HIGH": "🛑",
            "WARNING": "⚠️",
            "INFO": "ℹ️",
            "SUCCESS": "✅",
        }
        icon = severity_icons.get(severity.upper(), "📢")
        
        text = f"{icon} *{title}*\n\n"
        text += f"*Event:* `{event_type}`\n"
        text += f"*Severity:* `{severity.upper()}`\n"
        text += f"*Time (WIB):* `{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}`\n\n"
        text += f"{message}\n"
        
        if details:
            details_str = json.dumps(details, indent=2, default=str)
            if len(details_str) > 1000:
                details_str = details_str[:1000] + "\n... (truncated)"
            text += f"\n```json\n{details_str}\n```"

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            if not self._http_session or self._http_session.closed:
                self._http_session = aiohttp.ClientSession()
                
            async with self._http_session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                if resp.status == 200:
                    now = time.time()
                    self._last_sent_time = now
                    self._event_last_sent[event_type] = now
                    self._event_payload_hashes[event_type] = payload_hash
                    logger.info(f"[TelegramNotifier] 📤 Alert sent successfully: [{event_type}] {title}")
                    return True
                else:
                    err_body = await resp.text()
                    logger.error(f"[TelegramNotifier] Failed to send telegram alert (HTTP {resp.status}): {err_body}")
                    return False
        except Exception as e:
            logger.error(f"[TelegramNotifier] Exception while dispatching alert: {e}")
            return False

    def send_alert_non_blocking(
        self,
        event_type: str,
        title: str,
        message: str,
        severity: str = "HIGH",
        details: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> None:
        """
        Completely fire-and-forget: Spawns async task in running loop.
        Guaranteed 0ms latency impact on trading caller.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self.send_alert(
                    event_type=event_type,
                    title=title,
                    message=message,
                    severity=severity,
                    details=details,
                    force=force,
                )
            )
        except RuntimeError:
            # No running event loop (e.g. synch script)
            pass

    async def close(self) -> None:
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

telegram_notifier = TelegramNotifier()
