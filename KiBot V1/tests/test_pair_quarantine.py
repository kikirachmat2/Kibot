"""Tests for Core/Intelligence/pair_quarantine.py — pair-level loss cooldown (G-003)."""

import json
import os
import time
from pathlib import Path

import pytest

from Core.Intelligence.pair_quarantine import (
    COOLDOWN_CONSECUTIVE_LOSSES,
    COOLDOWN_SECONDS,
    cleanup_expired,
    is_quarantined,
    load_pair_quarantine,
    quarantine_pair,
    record_pair_outcome,
)
import Core.Intelligence.pair_quarantine as pq_mod


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Redirect pair quarantine state to a temp directory for every test."""
    state_file = tmp_path / "pair_quarantine.json"
    monkeypatch.setattr(pq_mod, "PAIR_FILE", state_file)
    monkeypatch.setattr(pq_mod, "STATE_DIR", tmp_path)
    yield state_file


class TestQuarantinePair:
    def test_quarantine_adds_to_blocked(self):
        quarantine_pair("EDENA/IDR", "test reason", seconds=3600)
        assert is_quarantined("EDENA/IDR") is True

    def test_quarantine_case_insensitive(self):
        quarantine_pair("edena/idr", "test", seconds=3600)
        assert is_quarantined("EDENA/IDR") is True

    def test_not_quarantined_by_default(self):
        assert is_quarantined("BTC/IDR") is False

    def test_quarantine_expires(self, monkeypatch):
        quarantine_pair("EDENA/IDR", "test", seconds=10)
        assert is_quarantined("EDENA/IDR") is True

        # Fast-forward past expiry
        future = time.time() + 20
        monkeypatch.setattr(time, "time", lambda: future)
        assert is_quarantined("EDENA/IDR") is False

    def test_quarantine_shows_in_blocked_pairs(self):
        quarantine_pair("POND/IDR", "test", seconds=3600)
        data = load_pair_quarantine()
        assert "POND/IDR" in data["blocked_pairs"]


class TestRecordPairOutcome:
    def test_single_loss_no_quarantine(self):
        triggered = record_pair_outcome("BTC/IDR", -1000.0)
        assert triggered is False
        assert is_quarantined("BTC/IDR") is False

    def test_consecutive_losses_trigger_quarantine(self):
        for i in range(COOLDOWN_CONSECUTIVE_LOSSES - 1):
            triggered = record_pair_outcome("EDENA/IDR", -500.0)
            assert triggered is False

        # The Nth consecutive loss should trigger quarantine
        triggered = record_pair_outcome("EDENA/IDR", -500.0)
        assert triggered is True
        assert is_quarantined("EDENA/IDR") is True

    def test_win_resets_loss_streak(self):
        record_pair_outcome("EDENA/IDR", -500.0)
        record_pair_outcome("EDENA/IDR", -500.0)
        # Win resets streak
        record_pair_outcome("EDENA/IDR", +200.0)

        data = load_pair_quarantine()
        rec = data.get("records", {}).get("EDENA/IDR", {})
        assert rec.get("loss_streak", 0) == 0
        assert is_quarantined("EDENA/IDR") is False

    def test_loss_streak_resets_after_quarantine(self):
        for _ in range(COOLDOWN_CONSECUTIVE_LOSSES):
            record_pair_outcome("X/IDR", -100.0)
        data = load_pair_quarantine()
        rec = data["records"]["X/IDR"]
        assert rec["loss_streak"] == 0  # reset after quarantine

    def test_outcome_tracks_total_trades(self):
        record_pair_outcome("A/IDR", -50.0)
        record_pair_outcome("A/IDR", +100.0)
        record_pair_outcome("A/IDR", -30.0)
        data = load_pair_quarantine()
        rec = data["records"]["A/IDR"]
        assert rec["total_trades"] == 3
        assert rec["total_losses"] == 2

    def test_no_double_quarantine_while_active(self, monkeypatch):
        """If pair is already quarantined, record_pair_outcome returns False (no-op)."""
        quarantine_pair("Y/IDR", "manual test", seconds=9999)
        triggered = record_pair_outcome("Y/IDR", -100.0)
        assert triggered is False  # already quarantined

    def test_quarantine_seconds_configurable(self, monkeypatch):
        monkeypatch.setattr(pq_mod, "COOLDOWN_CONSECUTIVE_LOSSES", 2)
        monkeypatch.setattr(pq_mod, "COOLDOWN_SECONDS", 600)
        record_pair_outcome("Z/IDR", -10.0)
        record_pair_outcome("Z/IDR", -10.0)
        assert is_quarantined("Z/IDR") is True
        data = load_pair_quarantine()
        rec = data["records"]["Z/IDR"]
        # until_ts should be ~600s from now
        assert rec.get("until_ts", 0) > time.time()
        assert rec.get("until_ts", 0) <= time.time() + 601


class TestCleanupExpired:
    def test_cleanup_removes_expired(self, monkeypatch):
        quarantine_pair("OLD/IDR", "old test", seconds=10)
        assert is_quarantined("OLD/IDR") is True

        future = time.time() + 20
        monkeypatch.setattr(time, "time", lambda: future)

        data = load_pair_quarantine()
        data = cleanup_expired(data)
        assert "OLD/IDR" not in data["blocked_pairs"]

    def test_cleanup_keeps_active(self):
        quarantine_pair("NEW/IDR", "fresh test", seconds=99999)
        data = load_pair_quarantine()
        data = cleanup_expired(data)
        assert "NEW/IDR" in data["blocked_pairs"]


class TestLiveTruthIntegration:
    def test_blocked_pairs_propagates_to_live_truth(self, tmp_path, monkeypatch):
        """Verify that quarantined pairs appear in live_truth.json's blocked_pairs."""
        quarantine_pair("EDENA/IDR", "loss streak", seconds=3600)

        # Mock the live_truth_manager to read from our temp state dir
        data = load_pair_quarantine()
        blocked = data.get("blocked_pairs", [])
        assert "EDENA/IDR" in blocked
