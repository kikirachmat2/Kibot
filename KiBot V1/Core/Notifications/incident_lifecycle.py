"""
Incident Lifecycle & Alert Escalation Tracker for Sovereign KiBot.

Operating Principles:
1. First seen incident -> URGENT alert immediately.
2. Persistent incident (>15m) -> Re-alert once as PERSISTENT CONFIRMATION.
3. Persistent incident (>2 alerts) -> Downgrade from URGENT; send max 1x/24h as DAILY STATUS (never silent total).
4. Reason/Signature change -> Instantly reset count to 0, treat as NEW incident -> URGENT immediately.
5. Operator ACK -> Mute alerts for specified duration unless signature changes.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from Core.Support.ki_config import STATE_DIR

LIFECYCLE_STATE_FILE = STATE_DIR / "incident_lifecycle.json"
PERSISTENCE_CONFIRM_SEC = 900.0   # 15 minutes
DAILY_REMINDER_SEC = 86400.0      # 24 hours
RESOLUTION_DEBOUNCE_SEC = 1800.0  # 30 minutes grace period against flapping


class IncidentLifecycleTracker:
    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = Path(state_file) if state_file else LIFECYCLE_STATE_FILE
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

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

    def _read_state(self, fh) -> Dict[str, Any]:
        fh.seek(0)
        raw = fh.read().strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_state(self, fh, state: Dict[str, Any]) -> None:
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except Exception:
            pass

    def evaluate_incident(
        self,
        incident_key: str,
        signature: str,
        now: Optional[float] = None,
    ) -> Tuple[bool, str, str]:
        """
        Evaluate whether an alert should be dispatched and with what severity title.

        Returns:
            Tuple[bool, str, str]: (should_send, severity, title_prefix)
            where severity is one of:
                - "URGENT"
                - "PERSISTENT_CONFIRMATION"
                - "DAILY_STATUS"
                - "COOLDOWN_WAITING_PERSISTENCE"
                - "COOLDOWN_DAILY_STATUS"
                - "ACKNOWLEDGED"
        """
        now = time.time() if now is None else float(now)
        key = str(incident_key or "default_incident").strip()
        sig = str(signature or "").strip()

        fh = self._lock_file()
        try:
            state = self._read_state(fh)
            entry = state.setdefault(key, {
                "incident_key": key,
                "signature": "",
                "first_seen_ts": now,
                "last_sent_ts": 0.0,
                "alert_count": 0,
                "last_severity": "",
                "acknowledged_until": 0.0,
                "acknowledged_reason": "",
            })

            prev_sig = str(entry.get("signature") or "")
            is_resolved = bool(entry.get("resolved", False))

            # ── 1. RESOLUTION & FLAPPING CHECK ──
            if is_resolved:
                resolved_at = float(entry.get("resolved_at", 0.0) or 0.0)
                time_since_resolve = max(0.0, now - resolved_at)

                if time_since_resolve < RESOLUTION_DEBOUNCE_SEC:
                    # Condition reoccurred within grace period: this is FLAPPING!
                    entry["resolved"] = False
                    entry.pop("resolved_at", None)

                    if prev_sig and prev_sig == sig:
                        # Same signature -> retain existing alert_count & escalation level!
                        # Do NOT reset alert_count! Fall through to ladder below.
                        pass
                    else:
                        # Reason changed during flapping -> treat as new reason
                        entry["signature"] = sig
                        entry["alert_count"] = 0
                        entry["first_seen_ts"] = now
                        entry["acknowledged_until"] = 0.0
                        entry["acknowledged_reason"] = ""
                else:
                    # Cleanly resolved for >30m -> genuinely new occurrence
                    entry["resolved"] = False
                    entry.pop("resolved_at", None)
                    entry["signature"] = sig
                    entry["alert_count"] = 0
                    entry["first_seen_ts"] = now
                    entry["acknowledged_until"] = 0.0
                    entry["acknowledged_reason"] = ""

            # ── 2. SIGNATURE COMPARISON (Active Incident Reason Changed?) ──
            elif prev_sig and prev_sig != sig:
                entry["signature"] = sig
                entry["alert_count"] = 0
                entry["first_seen_ts"] = now
                entry["acknowledged_until"] = 0.0  # Clear ACK on new condition
                entry["acknowledged_reason"] = ""
            elif not prev_sig:
                entry["signature"] = sig
                entry["first_seen_ts"] = now

            # ── 3. OPERATOR ACKNOWLEDGEMENT CHECK ──
            ack_until = float(entry.get("acknowledged_until", 0.0) or 0.0)
            if now < ack_until:
                self._write_state(fh, state)
                return False, "ACKNOWLEDGED", ""

            count = int(entry.get("alert_count", 0) or 0)
            first_seen = float(entry.get("first_seen_ts", now) or now)
            last_sent = float(entry.get("last_sent_ts", 0.0) or 0.0)

            # ── 4. ESCALATION LADDER ──
            # Level 0: First time detected (or reason just changed) -> URGENT immediately
            if count == 0:
                entry["alert_count"] = 1
                entry["last_sent_ts"] = now
                entry["last_severity"] = "URGENT"
                self._write_state(fh, state)
                return True, "URGENT", "🚨 *URGENT SYSTEM ALERT*"

            # Level 1: Persistent check (>15m from first seen and >15m from first alert)
            if count == 1:
                if (now - first_seen) >= PERSISTENCE_CONFIRM_SEC and (now - last_sent) >= PERSISTENCE_CONFIRM_SEC:
                    entry["alert_count"] = 2
                    entry["last_sent_ts"] = now
                    entry["last_severity"] = "PERSISTENT_CONFIRMATION"
                    self._write_state(fh, state)
                    return True, "PERSISTENT_CONFIRMATION", "⚠️ *PERSISTENT BLOCKER CONFIRMED*"
                self._write_state(fh, state)
                return False, "COOLDOWN_WAITING_PERSISTENCE", ""

            # Level 2+: Persistent condition (>2 alerts already sent)
            # Never send as URGENT. Send max 1x per 24 hours as visible daily reminder.
            if (now - last_sent) >= DAILY_REMINDER_SEC:
                entry["alert_count"] = count + 1
                entry["last_sent_ts"] = now
                entry["last_severity"] = "DAILY_STATUS"
                self._write_state(fh, state)
                return True, "DAILY_STATUS", "ℹ️ *DAILY RUNTIME BLOCKER STATUS*"

            self._write_state(fh, state)
            return False, "COOLDOWN_DAILY_STATUS", ""
        finally:
            self._unlock_file(fh)

    def acknowledge(
        self,
        incident_key: str,
        hours: float = 24.0,
        note: str = "",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Acknowledge an incident for a given duration (default 24h)."""
        now = time.time() if now is None else float(now)
        key = str(incident_key or "default_incident").strip()
        ack_until = now + (float(hours) * 3600.0)

        fh = self._lock_file()
        try:
            state = self._read_state(fh)
            entry = state.setdefault(key, {
                "incident_key": key,
                "signature": "",
                "first_seen_ts": now,
                "last_sent_ts": 0.0,
                "alert_count": 0,
                "last_severity": "",
            })
            entry["acknowledged_until"] = ack_until
            entry["acknowledged_reason"] = str(note or "Operator acknowledged").strip()
            self._write_state(fh, state)
            return entry
        finally:
            self._unlock_file(fh)

    def resolve(self, incident_key: str, now: Optional[float] = None) -> bool:
        """
        Mark an incident resolved with debounce grace period.
        Preserves history so that flapping conditions within
        RESOLUTION_DEBOUNCE_SEC do not reset the escalation ladder.
        """
        now = time.time() if now is None else float(now)
        key = str(incident_key or "").strip()
        fh = self._lock_file()
        try:
            state = self._read_state(fh)
            if key in state:
                entry = state[key]
                was_active = int(entry.get("alert_count", 0) or 0) > 0 and not entry.get("resolved", False)
                entry["resolved"] = True
                entry["resolved_at"] = now
                entry["last_severity"] = "RESOLVED"
                self._write_state(fh, state)
                return was_active
            return False
        finally:
            self._unlock_file(fh)

    def get_all_incidents(self, include_resolved: bool = True) -> Dict[str, Any]:
        """Get snapshot of all tracked incidents."""
        fh = self._lock_file()
        try:
            state = self._read_state(fh)
            if include_resolved:
                return state
            return {k: v for k, v in state.items() if not v.get("resolved", False)}
        finally:
            self._unlock_file(fh)
