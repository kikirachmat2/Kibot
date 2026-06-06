from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from Core.sovereign_notifier import SovereignNotifier

ALLOWED_EVENTS = {
    "SYSTEM_STARTED_LIVE_ONLY",
    "SYSTEM_RECOVERED",
    "EMERGENCY_STOP",
    "DAILY_LOSS_LOCK",
    "WALLET_RECONCILIATION_MISMATCH",
    "ORDER_STUCK",
    "ORDER_FILLED_SUMMARY",
    "POSITION_EXITED_SUMMARY",
    "VENUE_DOWN",
    "RPC_DOWN",
    "API_AUTH_FAILED",
    "SECRET_MISSING",
    "DUST_CREATED",
    "PAIR_QUARANTINED",
    "DAILY_SUMMARY",
    "LIVE_TRUTH_REFRESH_FAILED",
}


@dataclass
class _DedupState:
    last_sent_at: Dict[str, float] = field(default_factory=dict)
    last_payload_hash: Dict[str, str] = field(default_factory=dict)


class TelegramExceptionNotifier:
    def __init__(self) -> None:
        self.notifier = SovereignNotifier()
        self.state = _DedupState()
        self.cooldown_sec = int(getattr(self.notifier.throttle, "global_min_interval_sec", 30) or 30)
        self.event_cooldown_sec = int(getattr(self.notifier.throttle, "incident_cooldown_sec", 3600) or 3600)

    def _hash_payload(self, event: str, message: str, payload: Optional[Dict[str, Any]]) -> str:
        raw = json.dumps(
            {"event": event, "message": message, "payload": payload or {}},
            sort_keys=True,
            default=str,
            ensure_ascii=True,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _dedupe_allows(self, event: str, payload_hash: str) -> bool:
        now = time.time()
        last_at = float(self.state.last_sent_at.get(event, 0.0) or 0.0)
        last_hash = self.state.last_payload_hash.get(event, "")
        if last_hash == payload_hash and now - last_at < self.event_cooldown_sec:
            return False
        if now - last_at < self.cooldown_sec:
            return False
        self.state.last_sent_at[event] = now
        self.state.last_payload_hash[event] = payload_hash
        return True

    async def notify_exception(
        self,
        *,
        event_type: str,
        title: str,
        message: str,
        severity: str = "HIGH",
        payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        event = str(event_type or "").upper().strip()
        if event not in ALLOWED_EVENTS:
            return False
        payload_hash = self._hash_payload(event, message, payload)
        if not self._dedupe_allows(event, payload_hash):
            return False
        body = f"{title}\nSeverity: {severity}\nEvent: {event}\n{message}"
        if payload:
            body += f"\n{json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)}"
        return await self.notifier.send_message(
            body,
            parse_mode=None,
            incident_key=f"{event}:{datetime.now(timezone.utc).date().isoformat()}",
            channel="exceptions",
            min_interval_sec=self.cooldown_sec,
            dedupe_window_sec=self.event_cooldown_sec,
            incident_cooldown_sec=self.event_cooldown_sec,
            force=True,
        )

    async def notify_trade_summary(
        self,
        *,
        venue: str,
        pair: str,
        side: str,
        entry_price: Any = None,
        exit_price: Any = None,
        size: Any = None,
        gross_pnl: Any = None,
        fee: Any = None,
        net_pnl: Any = None,
        reason: str = "",
        hold_minutes: Any = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        event = "ORDER_FILLED_SUMMARY"
        payload_hash = self._hash_payload(
            event,
            f"{venue}:{pair}:{side}:{entry_price}:{exit_price}:{size}:{net_pnl}",
            payload,
        )
        if not self._dedupe_allows(f"{event}:{venue}:{pair}:{side}", payload_hash):
            return False
        body = (
            "LIVE TRADE CLOSED\n"
            f"Venue: {venue}\n"
            f"Pair: {pair}\n"
            f"Side: {side}\n"
            f"Entry: {entry_price}\n"
            f"Exit: {exit_price}\n"
            f"Size: {size}\n"
            f"Gross PnL: {gross_pnl}\n"
            f"Fee: {fee}\n"
            f"Net PnL: {net_pnl}\n"
            f"Reason: {reason}\n"
            f"Hold: {hold_minutes}"
        )
        if payload:
            body += f"\n{json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)}"
        return await self.notifier.send_message(
            body,
            parse_mode=None,
            incident_key=f"{event}:{venue}:{pair}:{datetime.now(timezone.utc).date().isoformat()}",
            channel="trade_summary",
            min_interval_sec=self.cooldown_sec,
            dedupe_window_sec=self.event_cooldown_sec,
            incident_cooldown_sec=self.event_cooldown_sec,
            force=True,
        )

    async def notify(self, event_type: str, message: str, *, payload: Optional[Dict[str, Any]] = None) -> bool:
        return await self.notify_exception(
            event_type=event_type,
            title=f"[{str(event_type or '').upper()}]",
            message=message,
            severity="HIGH",
            payload=payload,
        )

    def notify_sync(self, event_type: str, message: str, *, payload: Optional[Dict[str, Any]] = None) -> bool:
        try:
            return asyncio.run(self.notify(event_type, message, payload=payload))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.notify(event_type, message, payload=payload))
