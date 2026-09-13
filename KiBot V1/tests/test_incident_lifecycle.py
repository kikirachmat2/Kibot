from __future__ import annotations

import time
from pathlib import Path
import pytest

from Core.Notifications.incident_lifecycle import (
    IncidentLifecycleTracker,
    PERSISTENCE_CONFIRM_SEC,
    DAILY_REMINDER_SEC,
)


def test_incident_lifecycle_escalation_ladder(tmp_path: Path):
    state_file = tmp_path / "test_lifecycle.json"
    tracker = IncidentLifecycleTracker(state_file=state_file)

    t0 = 1000000.0
    key = "runtime_orders_blocked_semantic"
    sig_a = "orders_off|reason=indodax_balance_unavailable"

    # 1. Level 0: First time seen -> URGENT immediately
    send, sev, title = tracker.evaluate_incident(key, sig_a, now=t0)
    assert send is True
    assert sev == "URGENT"
    assert "🚨 *URGENT SYSTEM ALERT*" in title

    # 2. Within 15 minutes (< 900s) -> Cooldown waiting persistence
    send, sev, _ = tracker.evaluate_incident(key, sig_a, now=t0 + 300.0)  # 5m later
    assert send is False
    assert sev == "COOLDOWN_WAITING_PERSISTENCE"

    send, sev, _ = tracker.evaluate_incident(key, sig_a, now=t0 + 600.0)  # 10m later
    assert send is False
    assert sev == "COOLDOWN_WAITING_PERSISTENCE"

    # 3. At >= 15 minutes (900s) -> Persistent Confirmation
    t_15m = t0 + PERSISTENCE_CONFIRM_SEC + 1.0
    send, sev, title = tracker.evaluate_incident(key, sig_a, now=t_15m)
    assert send is True
    assert sev == "PERSISTENT_CONFIRMATION"
    assert "⚠️ *PERSISTENT BLOCKER CONFIRMED*" in title

    # 4. Subsequent checks within 24 hours -> suppressed (COOLDOWN_DAILY_STATUS)
    # E.g. at 1 hour later (which previously spammed every hour)
    send, sev, _ = tracker.evaluate_incident(key, sig_a, now=t_15m + 3600.0)
    assert send is False
    assert sev == "COOLDOWN_DAILY_STATUS"

    # E.g. at 12 hours later
    send, sev, _ = tracker.evaluate_incident(key, sig_a, now=t_15m + 43200.0)
    assert send is False
    assert sev == "COOLDOWN_DAILY_STATUS"

    # 5. At >= 24 hours -> Daily Status reminder (never completely silent)
    t_24h = t_15m + DAILY_REMINDER_SEC + 1.0
    send, sev, title = tracker.evaluate_incident(key, sig_a, now=t_24h)
    assert send is True
    assert sev == "DAILY_STATUS"
    assert "ℹ️ *DAILY RUNTIME BLOCKER STATUS*" in title

    # 6. Again within the next 24 hours -> suppressed
    send, sev, _ = tracker.evaluate_incident(key, sig_a, now=t_24h + 3600.0)
    assert send is False
    assert sev == "COOLDOWN_DAILY_STATUS"


def test_reason_signature_change_resets_escalation_to_urgent(tmp_path: Path):
    """
    Mandatory scenario:
    Blocker A persists for 3 days (submerged into daily status).
    Then the reason changes from Blocker A to Blocker B.
    Must IMMEDIATELY reset alert_count to 0 and fire URGENT alert again!
    """
    state_file = tmp_path / "test_lifecycle.json"
    tracker = IncidentLifecycleTracker(state_file=state_file)

    t0 = 1000000.0
    key = "runtime_orders_blocked_semantic"
    sig_a = "orders_off|reason=indodax_balance_unavailable"
    sig_b = "orders_off|reason=risk_circuit_broken"

    # Day 0: Initial alert
    tracker.evaluate_incident(key, sig_a, now=t0)
    # 15m persistent alert
    tracker.evaluate_incident(key, sig_a, now=t0 + PERSISTENCE_CONFIRM_SEC + 1.0)
    # Day 1: Daily reminder
    tracker.evaluate_incident(key, sig_a, now=t0 + DAILY_REMINDER_SEC + 1000.0)
    # Day 2: Daily reminder
    tracker.evaluate_incident(key, sig_a, now=t0 + (2 * DAILY_REMINDER_SEC) + 1000.0)
    # Day 3: Blocker A still persistent, suppressed mid-day
    t_day3_mid = t0 + (2.5 * DAILY_REMINDER_SEC)
    send, sev, _ = tracker.evaluate_incident(key, sig_a, now=t_day3_mid)
    assert send is False
    assert sev == "COOLDOWN_DAILY_STATUS"

    # NOW: Reason changes to Blocker B (sig_b) at t_day3_mid + 60s
    t_changed = t_day3_mid + 60.0
    send, sev, title = tracker.evaluate_incident(key, sig_b, now=t_changed)

    # MUST IMMEDIATELY BE URGENT AGAIN!
    assert send is True
    assert sev == "URGENT"
    assert "🚨 *URGENT SYSTEM ALERT*" in title

    # Verify state was reset
    all_incidents = tracker.get_all_incidents()
    entry = all_incidents[key]
    assert entry["alert_count"] == 1
    assert entry["signature"] == sig_b
    assert entry["first_seen_ts"] == t_changed


def test_operator_acknowledgement(tmp_path: Path):
    state_file = tmp_path / "test_lifecycle.json"
    tracker = IncidentLifecycleTracker(state_file=state_file)

    t0 = 1000000.0
    key = "runtime_orders_blocked_semantic"
    sig_a = "orders_off|reason=indodax_balance_unavailable"

    # Level 0 alert
    send, sev, _ = tracker.evaluate_incident(key, sig_a, now=t0)
    assert send is True

    # Operator acknowledges for 12 hours
    tracker.acknowledge(key, hours=12.0, note="Testing balance Rp 0 intentional", now=t0 + 60.0)

    # Persistent check at 15m -> Muted by ACK
    send, sev, _ = tracker.evaluate_incident(key, sig_a, now=t0 + 1000.0)
    assert send is False
    assert sev == "ACKNOWLEDGED"

    # At 6 hours -> Muted by ACK
    send, sev, _ = tracker.evaluate_incident(key, sig_a, now=t0 + 21600.0)
    assert send is False
    assert sev == "ACKNOWLEDGED"

    # At 12.1 hours -> ACK expired, evaluated under persistent rules (Level 1 persistent alert)
    send, sev, title = tracker.evaluate_incident(key, sig_a, now=t0 + 43560.0)
    assert send is True
    assert sev == "PERSISTENT_CONFIRMATION"


def test_signature_change_breaks_active_acknowledgement(tmp_path: Path):
    """
    If operator acknowledged incident for Blocker A, but condition shifts to Blocker B,
    the ACK must be immediately cleared and URGENT alert fired.
    """
    state_file = tmp_path / "test_lifecycle.json"
    tracker = IncidentLifecycleTracker(state_file=state_file)

    t0 = 1000000.0
    key = "runtime_orders_blocked_semantic"
    sig_a = "orders_off|reason=indodax_balance_unavailable"
    sig_b = "orders_off|reason=emergency_kill_switch"

    # Initial alert & operator ack
    tracker.evaluate_incident(key, sig_a, now=t0)
    tracker.acknowledge(key, hours=24.0, note="Waiting for deposit", now=t0 + 10.0)

    # Condition shifts to Blocker B while ACK is active
    send, sev, title = tracker.evaluate_incident(key, sig_b, now=t0 + 3600.0)
    assert send is True
    assert sev == "URGENT"
    assert "🚨 *URGENT SYSTEM ALERT*" in title

    # Check ACK was cleared
    entry = tracker.get_all_incidents()[key]
    assert entry["acknowledged_until"] == 0.0


def test_incident_resolution(tmp_path: Path):
    state_file = tmp_path / "test_lifecycle.json"
    tracker = IncidentLifecycleTracker(state_file=state_file)

    t0 = 1000000.0
    key = "test_incident"
    sig = "reason=testing"

    tracker.evaluate_incident(key, sig, now=t0)
    assert key in tracker.get_all_incidents()
    assert key in tracker.get_all_incidents(include_resolved=False)

    resolved = tracker.resolve(key, now=t0 + 10.0)
    assert resolved is True
    # Still preserved in all incidents (for anti-flapping history)
    assert key in tracker.get_all_incidents(include_resolved=True)
    # But excluded from active unresolved incidents
    assert key not in tracker.get_all_incidents(include_resolved=False)

    # Resolving again returns False (already resolved)
    assert tracker.resolve(key, now=t0 + 20.0) is False


def test_incident_flapping_suppression(tmp_path: Path):
    """
    CRITICAL ANTI-SPAM TEST:
    1. Incident occurs at t0 -> Level 0 URGENT sent (alert_count: 1).
    2. At t0 + 15m (900s) -> Level 1 PERSISTENT_CONFIRMATION sent (alert_count: 2).
    3. At t0 + 16m -> condition briefly clears (e.g. Indodax balance query succeeds for 1 cycle).
       tracker.resolve() is called!
    4. At t0 + 18m (2m later) -> condition recurs with SAME signature (Indodax API glitch).
       EVALUATE MUST NOT FIRE URGENT ALERT!
       MUST recognize flapping within 30m grace window and suppress alert!
    5. At t0 + 50m (>30m after resolution) -> condition recurs.
       Now considered genuinely fresh incident -> URGENT alert fired.
    """
    state_file = tmp_path / "test_lifecycle.json"
    tracker = IncidentLifecycleTracker(state_file=state_file)

    t0 = 1000000.0
    key = "runtime_orders_blocked_semantic"
    sig = "orders_off|reason=indodax_balance_unavailable"

    # 1. Level 0: First seen -> URGENT
    send, sev, _ = tracker.evaluate_incident(key, sig, now=t0)
    assert send is True
    assert sev == "URGENT"

    # 2. Level 1: At 15m -> PERSISTENT_CONFIRMATION
    send, sev, _ = tracker.evaluate_incident(key, sig, now=t0 + 901.0)
    assert send is True
    assert sev == "PERSISTENT_CONFIRMATION"

    # 3. Brief resolution at 16m
    t_resolve = t0 + 960.0
    assert tracker.resolve(key, now=t_resolve) is True

    # 4. FLAPPING: Recur at 18m (2m after resolve, within 30m debounce window)
    send, sev, _ = tracker.evaluate_incident(key, sig, now=t0 + 1080.0)
    # MUST BE SUPPRESSED! NOT URGENT!
    assert send is False
    assert sev == "COOLDOWN_DAILY_STATUS"

    # Flapping again at 25m (9m after resolve)
    send, sev, _ = tracker.evaluate_incident(key, sig, now=t0 + 1500.0)
    assert send is False
    assert sev == "COOLDOWN_DAILY_STATUS"

    # Resolved cleanly at 26m
    t_clean_resolve = t0 + 1560.0
    assert tracker.resolve(key, now=t_clean_resolve) is True

    # 5. Genuine new occurrence: Recur at t_clean_resolve + 31 minutes (>30m debounce window)
    t_fresh = t_clean_resolve + 1801.0
    send, sev, title = tracker.evaluate_incident(key, sig, now=t_fresh)
    assert send is True
    assert sev == "URGENT"
    assert "🚨 *URGENT SYSTEM ALERT*" in title

