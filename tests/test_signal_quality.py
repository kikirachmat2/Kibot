"""Tests for Core/Intelligence/signal_quality.py"""

import pytest
from Core.Intelligence.signal_quality import (
    SignalGrade,
    evaluate_signal_quality,
    batch_evaluate,
)


class TestEvaluateSignalQuality:
    def test_all_green_returns_strong(self):
        sq = evaluate_signal_quality(
            spread_pct=0.003,
            volume_ratio=1.5,
            leadlag_score=0.3,
            daily_volatility_pct=0.05,
            data_age_seconds=10.0,
        )
        assert sq.grade == SignalGrade.STRONG
        assert sq.score == 1.0
        assert sq.is_tradeable is True

    def test_all_missing_returns_reject(self):
        sq = evaluate_signal_quality()
        assert sq.grade == SignalGrade.REJECT
        assert sq.is_tradeable is False

    def test_spread_too_wide(self):
        sq = evaluate_signal_quality(
            spread_pct=0.02,    # 2% — over limit
            volume_ratio=1.0,
            leadlag_score=0.5,
            daily_volatility_pct=0.05,
            data_age_seconds=5.0,
        )
        assert sq.spread_ok is False

    def test_stale_data_fails_freshness(self):
        sq = evaluate_signal_quality(
            spread_pct=0.003,
            volume_ratio=1.0,
            leadlag_score=0.3,
            daily_volatility_pct=0.05,
            data_age_seconds=120.0,   # 2 min stale
        )
        assert sq.data_fresh is False

    def test_bearish_leadlag_fails_alignment(self):
        sq = evaluate_signal_quality(
            spread_pct=0.003,
            volume_ratio=1.0,
            leadlag_score=-0.4,   # bearish
            daily_volatility_pct=0.05,
            data_age_seconds=5.0,
        )
        assert sq.leadlag_aligned is False

    def test_volatility_too_high_fails(self):
        sq = evaluate_signal_quality(
            spread_pct=0.003,
            volume_ratio=1.0,
            leadlag_score=0.3,
            daily_volatility_pct=0.25,   # 25% — too wild
            data_age_seconds=5.0,
        )
        assert sq.volatility_ok is False

    def test_grade_marginal_two_passing_dims(self):
        sq = evaluate_signal_quality(
            spread_pct=0.003,    # pass
            volume_ratio=1.0,    # pass
            leadlag_score=-0.4,  # fail
            daily_volatility_pct=0.25,  # fail
            data_age_seconds=120.0,     # fail
        )
        assert sq.grade == SignalGrade.MARGINAL

    def test_batch_evaluate_attaches_quality(self):
        candidates = [
            {"spread_pct": 0.003, "volume_ratio": 1.5, "leadlag_score": 0.3,
             "daily_volatility_pct": 0.05, "data_age_seconds": 5.0},
            {"spread_pct": 0.05},   # mostly failing
        ]
        result = batch_evaluate(candidates)
        assert "signal_quality" in result[0]
        assert "is_tradeable" in result[0]
        assert result[0]["is_tradeable"] is True
        assert result[1]["is_tradeable"] is False
