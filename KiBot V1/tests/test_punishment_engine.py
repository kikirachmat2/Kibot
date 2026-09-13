"""Tests for Core/Intelligence/punishment_engine.py"""

import time
import tempfile
from pathlib import Path
import pytest
from Core.Intelligence.punishment_engine import (
    PunishmentEngine,
    LOSS_STREAK_LIMIT,
    QUARANTINE_SECONDS,
)


@pytest.fixture
def engine(tmp_path):
    state_file = tmp_path / "punishment_state.json"
    return PunishmentEngine(state_file=state_file)


class TestPunishmentEngine:
    def test_clean_strategy_not_quarantined(self, engine):
        assert engine.is_quarantined("BTC_momentum") is False

    def test_loss_streak_triggers_quarantine(self, engine):
        sid = "test_strat"
        for _ in range(LOSS_STREAK_LIMIT):
            engine.record_trade(sid, -0.01)
        assert engine.is_quarantined(sid) is True

    def test_win_resets_loss_streak(self, engine):
        sid = "strat_recover"
        engine.record_trade(sid, -0.01)
        engine.record_trade(sid, -0.01)
        engine.record_trade(sid, +0.02)   # win — streak reset
        rec = engine._records.get(sid)
        assert rec.loss_streak == 0

    def test_daily_drawdown_triggers_quarantine(self, engine):
        sid = "dd_strat"
        # Three losses of 1.1% each → total 3.3% > 3% limit
        for _ in range(3):
            engine.record_trade(sid, -0.011)
        assert engine.is_quarantined(sid) is True

    def test_force_clear_lifts_quarantine(self, engine):
        sid = "clear_me"
        for _ in range(LOSS_STREAK_LIMIT):
            engine.record_trade(sid, -0.02)
        assert engine.is_quarantined(sid) is True
        engine.force_clear(sid)
        assert engine.is_quarantined(sid) is False

    def test_severity_increases_on_loss(self, engine):
        sid = "sev_strat"
        engine.record_trade(sid, -0.01)
        assert engine.get_severity(sid) > 0.0

    def test_severity_decreases_on_win(self, engine):
        sid = "sev_win"
        engine.record_trade(sid, -0.01)
        engine.record_trade(sid, -0.01)
        sev_after_losses = engine.get_severity(sid)
        engine.record_trade(sid, +0.02)
        assert engine.get_severity(sid) < sev_after_losses

    def test_state_persists_after_reload(self, tmp_path):
        state_file = tmp_path / "p_state.json"
        e1 = PunishmentEngine(state_file=state_file)
        sid = "persist_strat"
        e1.record_trade(sid, -0.01)
        sev1 = e1.get_severity(sid)

        e2 = PunishmentEngine(state_file=state_file)
        assert e2.get_severity(sid) == sev1
