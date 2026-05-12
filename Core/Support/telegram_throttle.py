from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests

ROOT = Path(__file__).resolve().parent.parent.parent
TELEGRAM_STATE_FILE = ROOT / "state" / "telegram_throttle.json"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _normalize_message(message: Any) -> str:
    text = str(message or "").strip()
    max_chars = _env_int("KIBOT_TELEGRAM_MAX_CHARS", 3800)
    if len(text) > max_chars:
        text = text[: max_chars - 20].rstrip() + "\n...[truncated]"
    return text


@dataclass(frozen=True)
class TelegramReservation:
    token: str
    channel: str
    message_hash: str
    incident_key: Optional[str]
    claimed_at: float
    claim_expires_at: float
    min_interval_sec: int
    dedupe_window_sec: int
    incident_cooldown_sec: int


class TelegramThrottle:
    """File-backed Telegram throttle with global dedupe and incident cooldowns."""

    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = Path(state_file) if state_file else TELEGRAM_STATE_FILE
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def _default_state(self) -> dict[str, Any]:
        return {
            "version": 1,
            "channels": {},
            "incidents": {},
        }

    def _read_state(self, fh) -> dict[str, Any]:
        fh.seek(0)
        raw = fh.read().strip()
        if not raw:
            return self._default_state()
        try:
            state = json.loads(raw)
        except Exception:
            return self._default_state()
        if not isinstance(state, dict):
            return self._default_state()
        state.setdefault("version", 1)
        state.setdefault("channels", {})
        state.setdefault("incidents", {})
        return state

    def _write_state(self, fh, state: dict[str, Any]) -> None:
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
        fh.flush()
        os.fsync(fh.fileno())

    def _lock_file(self):
        fh = self.state_file.open("a+", encoding="utf-8")
        fcntl.flock(fh, fcntl.LOCK_EX)
        return fh

    def _unlock_file(self, fh) -> None:
        try:
            fh.flush()
        except Exception:
            pass
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()

    def claim(
        self,
        message: Any,
        *,
        channel: str = "default",
        incident_key: Optional[str] = None,
        parse_mode: Optional[str] = "Markdown",
        min_interval_sec: Optional[int] = None,
        dedupe_window_sec: Optional[int] = None,
        incident_cooldown_sec: Optional[int] = None,
        claim_ttl_sec: Optional[int] = None,
        force: bool = False,
    ) -> tuple[bool, Optional[TelegramReservation], str]:
        normalized = _normalize_message(message)
        channel_name = (channel or "default").strip() or "default"
        min_interval_sec = min_interval_sec if min_interval_sec is not None else _env_int("KIBOT_TELEGRAM_MIN_INTERVAL_SEC", 30)
        dedupe_window_sec = dedupe_window_sec if dedupe_window_sec is not None else _env_int("KIBOT_TELEGRAM_DEDUPE_WINDOW_SEC", 900)
        incident_cooldown_sec = incident_cooldown_sec if incident_cooldown_sec is not None else _env_int("KIBOT_TELEGRAM_INCIDENT_COOLDOWN_SEC", 3600)
        claim_ttl_sec = claim_ttl_sec if claim_ttl_sec is not None else _env_int("KIBOT_TELEGRAM_CLAIM_TTL_SEC", 30)

        now = time.time()
        message_hash = hashlib.sha256(
            f"{channel_name}|{normalized}".encode("utf-8")
        ).hexdigest()
        token = uuid.uuid4().hex

        fh = self._lock_file()
        try:
            state = self._read_state(fh)
            channels = state.setdefault("channels", {})
            incidents = state.setdefault("incidents", {})
            channel_state = channels.setdefault(channel_name, {})

            current_claim = channel_state.get("claim", {})
            if isinstance(current_claim, dict):
                claim_expires_at = float(current_claim.get("claim_expires_at", 0) or 0)
                if claim_expires_at > now and current_claim.get("token"):
                    return False, None, "IN_FLIGHT"
                if claim_expires_at and claim_expires_at <= now:
                    channel_state.pop("claim", None)

            if not force:
                last_sent_at = float(channel_state.get("last_sent_at", 0) or 0)
                if last_sent_at and now - last_sent_at < min_interval_sec:
                    return False, None, f"GLOBAL_COOLDOWN:{int(min_interval_sec - (now - last_sent_at))}"

                last_message_hash = str(channel_state.get("last_message_hash", ""))
                last_message_at = float(channel_state.get("last_message_at", 0) or 0)
                if last_message_hash == message_hash and last_message_at and now - last_message_at < dedupe_window_sec:
                    return False, None, f"DUPLICATE:{int(dedupe_window_sec - (now - last_message_at))}"

                if incident_key:
                    incident_state = incidents.setdefault(incident_key, {})
                    incident_last_sent = float(incident_state.get("last_sent_at", 0) or 0)
                    if incident_last_sent and now - incident_last_sent < incident_cooldown_sec:
                        return False, None, f"INCIDENT_COOLDOWN:{int(incident_cooldown_sec - (now - incident_last_sent))}"

            reservation = TelegramReservation(
                token=token,
                channel=channel_name,
                message_hash=message_hash,
                incident_key=incident_key,
                claimed_at=now,
                claim_expires_at=now + claim_ttl_sec,
                min_interval_sec=min_interval_sec,
                dedupe_window_sec=dedupe_window_sec,
                incident_cooldown_sec=incident_cooldown_sec,
            )
            channel_state["claim"] = {
                "token": reservation.token,
                "message_hash": reservation.message_hash,
                "incident_key": reservation.incident_key,
                "claimed_at": reservation.claimed_at,
                "claim_expires_at": reservation.claim_expires_at,
            }
            channels[channel_name] = channel_state
            state["channels"] = channels
            state["incidents"] = incidents
            self._write_state(fh, state)
            return True, reservation, "CLAIMED"
        finally:
            self._unlock_file(fh)

    def commit(self, reservation: TelegramReservation) -> bool:
        if not reservation:
            return False

        now = time.time()
        fh = self._lock_file()
        try:
            state = self._read_state(fh)
            channels = state.setdefault("channels", {})
            incidents = state.setdefault("incidents", {})
            channel_state = channels.setdefault(reservation.channel, {})
            claim = channel_state.get("claim", {})
            if not isinstance(claim, dict) or claim.get("token") != reservation.token:
                return False

            channel_state["last_sent_at"] = now
            channel_state["last_message_hash"] = reservation.message_hash
            channel_state["last_message_at"] = now
            channel_state.pop("claim", None)

            if reservation.incident_key:
                incident_state = incidents.setdefault(reservation.incident_key, {})
                incident_state["last_sent_at"] = now
                incident_state["last_message_hash"] = reservation.message_hash
                incident_state["last_message_at"] = now

            channels[reservation.channel] = channel_state
            state["channels"] = channels
            state["incidents"] = incidents
            self._write_state(fh, state)
            return True
        finally:
            self._unlock_file(fh)

    def release(self, reservation: TelegramReservation) -> bool:
        if not reservation:
            return False

        fh = self._lock_file()
        try:
            state = self._read_state(fh)
            channels = state.setdefault("channels", {})
            channel_state = channels.setdefault(reservation.channel, {})
            claim = channel_state.get("claim", {})
            if isinstance(claim, dict) and claim.get("token") == reservation.token:
                channel_state.pop("claim", None)
                channels[reservation.channel] = channel_state
                state["channels"] = channels
                self._write_state(fh, state)
                return True
            return False
        finally:
            self._unlock_file(fh)


_THROTTLE: Optional[TelegramThrottle] = None


def get_telegram_throttle() -> TelegramThrottle:
    global _THROTTLE
    if _THROTTLE is None:
        _THROTTLE = TelegramThrottle()
    return _THROTTLE


def telegram_send(
    message: str,
    parse_mode: str = "Markdown",
    incident_key: Optional[str] = None,
    channel: str = "default",
    min_interval_sec: Optional[int] = None,
    dedupe_window_sec: Optional[int] = None,
    incident_cooldown_sec: Optional[int] = None,
    claim_ttl_sec: Optional[int] = None,
    force: bool = False,
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
    timeout_sec: float = 10.0,
) -> bool:
    """Send a throttled Telegram message with duplicate suppression."""
    token = token or os.getenv("KIBOT_TELEGRAM_TOKEN")
    chat_id = chat_id or os.getenv("KIBOT_TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False

    throttle = get_telegram_throttle()
    allowed, reservation, reason = throttle.claim(
        message,
        channel=channel,
        incident_key=incident_key,
        parse_mode=parse_mode,
        min_interval_sec=min_interval_sec,
        dedupe_window_sec=dedupe_window_sec,
        incident_cooldown_sec=incident_cooldown_sec,
        claim_ttl_sec=claim_ttl_sec,
        force=force,
    )
    if not allowed or not reservation:
        print(f"[TELEGRAM][THROTTLED] {reason}", flush=True)
        return False

    text = _normalize_message(message)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        resp = requests.post(url, json=payload, timeout=timeout_sec)
        if 200 <= resp.status_code < 300:
            throttle.commit(reservation)
            return True

        if resp.status_code == 400 and parse_mode:
            fallback = dict(payload)
            fallback.pop("parse_mode", None)
            resp = requests.post(url, json=fallback, timeout=timeout_sec)
            if 200 <= resp.status_code < 300:
                throttle.commit(reservation)
                return True

        print(f"[TELEGRAM][ERROR] HTTP {resp.status_code}: {resp.text[:500]}", flush=True)
    except Exception as exc:
        print(f"[TELEGRAM][ERROR] {exc}", flush=True)

    throttle.release(reservation)
    return False


async def telegram_send_async(*args: Any, **kwargs: Any) -> bool:
    return await asyncio.to_thread(telegram_send, *args, **kwargs)
