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
from collections import deque
from config import settings

logger = logging.getLogger("KiBotV2.Notifications")

class TelegramNotifier:
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        global_min_interval_s: float = 3.0,
        event_cooldown_s: float = 300.0,
        allowed_chat_ids: Optional[set] = None,
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
        self._consecutive_failures: int = 0
        
        # 2a. Whitelist of authorized Chat IDs
        self._allowed_chat_ids = self._build_allowed_chat_ids(allowed_chat_ids)

        # 2c. Rate Limiting: Max 100 messages per hour (sliding window)
        self._hourly_sent_timestamps: deque = deque()
        self._max_messages_per_hour: int = 100

        # 2d. Anomaly Burst Detection: 5+ messages in 1 minute
        self._minute_sent_timestamps: deque = deque()
        self._last_anomaly_alert_time: float = 0.0
        
        if not self.bot_token or not self.chat_id:
            logger.warning("[TelegramNotifier] ⚠️ Telegram credentials missing (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set). Notifications will be safely skipped.")
            self._warned_missing_credentials = True
        else:
            logger.info(f"[TelegramNotifier] ✅ Initialized with configured Telegram chat (Whitelist: {sorted(list(self._allowed_chat_ids))}).")

    def _build_allowed_chat_ids(self, extra_ids: Optional[set] = None) -> set:
        allowed = set()
        candidates = [
            self.chat_id,
            getattr(settings, "TELEGRAM_CHAT_ID", None),
            os.getenv("TELEGRAM_CHAT_ID"),
            os.getenv("KIBOT_TELEGRAM_CHAT_ID"),
        ]
        if extra_ids:
            candidates.extend(extra_ids)
        for c in candidates:
            if c is not None and str(c).strip():
                clean = str(c).strip().strip('"').strip("'")
                if clean:
                    allowed.add(clean)
                    try:
                        allowed.add(str(int(clean)))
                    except (ValueError, TypeError):
                        pass
        return allowed

    def is_chat_id_allowed(self, target_chat_id: Any) -> bool:
        if not target_chat_id:
            return False
        clean = str(target_chat_id).strip().strip('"').strip("'")
        if clean in self._allowed_chat_ids:
            return True
        try:
            return str(int(clean)) in self._allowed_chat_ids
        except (ValueError, TypeError):
            return False

    def _check_rate_limit(self, now: float) -> bool:
        """Rate limiting: Max 100 messages per hour."""
        cutoff_hour = now - 3600.0
        while self._hourly_sent_timestamps and self._hourly_sent_timestamps[0] < cutoff_hour:
            self._hourly_sent_timestamps.popleft()
        if len(self._hourly_sent_timestamps) >= self._max_messages_per_hour:
            logger.warning(f"[TelegramNotifier] ⚠️ Hourly rate limit exceeded ({len(self._hourly_sent_timestamps)}/100 msgs). Blocking dispatch.")
            return False
        return True

    def _record_sent_timestamp(self, now: float) -> None:
        self._hourly_sent_timestamps.append(now)
        self._minute_sent_timestamps.append(now)

    async def _check_and_alert_anomaly(self, now: float) -> None:
        """Anomaly detection: alert via fallback channel if 5+ messages dispatched in 1 minute."""
        cutoff_min = now - 60.0
        while self._minute_sent_timestamps and self._minute_sent_timestamps[0] < cutoff_min:
            self._minute_sent_timestamps.popleft()
        if len(self._minute_sent_timestamps) >= 5:
            if now - self._last_anomaly_alert_time > 300.0:  # 5 min cooldown
                self._last_anomaly_alert_time = now
                count = len(self._minute_sent_timestamps)
                logger.warning(f"[TelegramNotifier] 🚨 Anomaly detected: {count} messages dispatched in <60s! Dispatching fallback alert.")
                fallback_webhook = getattr(settings, "TELEGRAM_FALLBACK_WEBHOOK", "") or os.getenv("TELEGRAM_FALLBACK_WEBHOOK", "")
                if fallback_webhook:
                    await self._dispatch_fallback_webhook(
                        webhook_url=fallback_webhook,
                        event_type="TELEGRAM_BURST_ANOMALY",
                        severity="CRITICAL",
                        title="Telegram Outbound Burst Anomaly Detected",
                        message=f"Bot dispatched {count} outbound messages within 60 seconds (threshold: 5/min).",
                        details={"burst_count_1m": count, "hourly_count": len(self._hourly_sent_timestamps)},
                    )

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

    async def _handle_failure(
        self,
        event_type: str,
        severity: str,
        title: str,
        message: str,
        details: Optional[Dict[str, Any]],
        error_str: str,
    ) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= 3:
            logger.warning(f"[TelegramNotifier] ⚠️ Telegram failed {self._consecutive_failures}x consecutively! Triggering fallback channels.")
            # 1. Log to local file: logs/telegram_failures.log
            self._log_failure_locally(event_type, severity, title, message, error_str)
            # 2. Optional webhook (Discord/Slack)
            fallback_webhook = getattr(settings, "TELEGRAM_FALLBACK_WEBHOOK", "") or os.getenv("TELEGRAM_FALLBACK_WEBHOOK", "")
            if fallback_webhook:
                await self._dispatch_fallback_webhook(fallback_webhook, event_type, severity, title, message, details)

    def _log_failure_locally(self, event_type: str, severity: str, title: str, message: str, error_str: str) -> None:
        try:
            from pathlib import Path
            log_dir = getattr(settings, "LOG_DIR", Path(__file__).resolve().parent.parent / "logs")
            log_dir.mkdir(parents=True, exist_ok=True)
            fail_log = log_dir / "telegram_failures.log"
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            entry = (
                f"[{timestamp}] [FAILURE #{self._consecutive_failures}] [{severity.upper()}] [{event_type}] {title}\n"
                f"Error: {error_str}\n"
                f"Message: {message}\n"
                f"{'-'*70}\n"
            )
            with open(fail_log, "a", encoding="utf-8") as f:
                f.write(entry)
            logger.info(f"[TelegramNotifier] 💾 Logged failed alert to {fail_log}")
        except Exception as e:
            logger.error(f"[TelegramNotifier] Failed to write local fallback log: {e}")

    async def _dispatch_fallback_webhook(
        self,
        webhook_url: str,
        event_type: str,
        severity: str,
        title: str,
        message: str,
        details: Optional[Dict[str, Any]],
    ) -> bool:
        try:
            text = f"🚨 [KIBOT FALLBACK] [{severity.upper()}] {title}\nEvent: `{event_type}`\n{message}"
            if details:
                text += f"\n```json\n{json.dumps(details, indent=2, default=str)[:800]}\n```"
            payload = {
                "text": text,        # Slack format
                "content": text,     # Discord format
            }
            if not self._http_session or self._http_session.closed:
                self._http_session = aiohttp.ClientSession()
            async with self._http_session.post(webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                if resp.status in (200, 204):
                    logger.info(f"[TelegramNotifier] 🔀 Fallback webhook delivered successfully: {title}")
                    return True
                else:
                    logger.warning(f"[TelegramNotifier] Fallback webhook failed (HTTP {resp.status})")
                    return False
        except Exception as exc:
            logger.error(f"[TelegramNotifier] Fallback webhook dispatch exception: {exc}")
            return False

    async def send_alert(
        self,
        event_type: str,
        title: str,
        message: str,
        severity: str = "HIGH",
        details: Optional[Dict[str, Any]] = None,
        force: bool = False,
        chat_id: Optional[Any] = None,
    ) -> bool:
        """
        Asynchronously sends formatted alert to Telegram.
        Never raises uncaught exceptions.
        Guarded by chat_id whitelist and hourly rate limits.
        """
        target_chat_id = chat_id or self.chat_id
        if not self.is_chat_id_allowed(target_chat_id):
            logger.warning(f"[TelegramNotifier] BLOCKED unauthorized chat_id: {target_chat_id}")
            return False

        if not self.is_configured:
            if not self._warned_missing_credentials:
                logger.warning("[TelegramNotifier] Skipping alert (Telegram credentials not configured).")
                self._warned_missing_credentials = True
            return False

        now = time.time()
        if not self._check_rate_limit(now):
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
            "chat_id": str(target_chat_id),
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            if not self._http_session or self._http_session.closed:
                self._http_session = aiohttp.ClientSession()
                
            async with self._http_session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                if resp.status == 200:
                    self._last_sent_time = now
                    self._event_last_sent[event_type] = now
                    self._event_payload_hashes[event_type] = payload_hash
                    self._consecutive_failures = 0
                    self._record_sent_timestamp(now)
                    await self._check_and_alert_anomaly(now)
                    logger.info(f"[TelegramNotifier] 📤 Alert sent successfully: [{event_type}] {title}")
                    return True
                else:
                    err_body = await resp.text()
                    logger.error(f"[TelegramNotifier] Failed to send telegram alert (HTTP {resp.status}): {err_body}")
                    await self._handle_failure(event_type, severity, title, message, details, f"HTTP {resp.status}: {err_body}")
                    return False
        except Exception as e:
            logger.error(f"[TelegramNotifier] Exception while dispatching alert: {e}")
            await self._handle_failure(event_type, severity, title, message, details, str(e))
            return False

    async def send_message(self, chat_id: Any, text: str, parse_mode: str = "Markdown") -> bool:
        """
        Direct message sender with strict chat_id whitelist, rate limiting, and anomaly tracking.
        """
        if not self.is_chat_id_allowed(chat_id):
            logger.warning(f"[TelegramNotifier] BLOCKED unauthorized chat_id: {chat_id}")
            return False
            
        if not self.is_configured:
            return False

        now = time.time()
        if not self._check_rate_limit(now):
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": str(chat_id),
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        try:
            if not self._http_session or self._http_session.closed:
                self._http_session = aiohttp.ClientSession()
                
            async with self._http_session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                if resp.status == 200:
                    self._record_sent_timestamp(now)
                    await self._check_and_alert_anomaly(now)
                    logger.info(f"[TelegramNotifier] 📤 Direct message sent successfully to {chat_id}")
                    return True
                else:
                    err_body = await resp.text()
                    logger.error(f"[TelegramNotifier] Failed to send direct telegram message (HTTP {resp.status}): {err_body}")
                    return False
        except Exception as e:
            logger.error(f"[TelegramNotifier] Exception while sending direct message: {e}")
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
