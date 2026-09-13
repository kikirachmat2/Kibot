"""Tests for Core/Intelligence/expected_value.py"""

import pytest
from Core.Intelligence.expected_value import (
    compute_ev,
    batch_evaluate_ev,
    EV_MIN_THRESHOLD,
    MIN_RR_RATIO,
)


class TestComputeEV:
    def test_positive_ev_approved(self):
        # avg_win 2.5% vs avg_loss 0.8% → net R:R >> 1.5 after fees
        result = compute_ev(
            win_prob=0.60,
            avg_win_pct=0.025,
            avg_loss_pct=0.008,
        )
        assert result.approved is True
        assert result.ev_pct > 0

    def test_negative_ev_rejected(self):
        result = compute_ev(
            win_prob=0.30,
            avg_win_pct=0.005,
            avg_loss_pct=0.02,
        )
        assert result.approved is False
        assert len(result.rejection_reasons) > 0

    def test_rr_below_minimum_rejected(self):
        # Low RR even with decent win prob
        result = compute_ev(
            win_prob=0.65,
            avg_win_pct=0.005,
            avg_loss_pct=0.008,
            override_rr_threshold=1.5,
        )
        assert result.approved is False
        assert any("R:R" in r for r in result.rejection_reasons)

    def test_kelly_fraction_capped_at_25pct(self):
        result = compute_ev(
            win_prob=0.90,
            avg_win_pct=0.10,
            avg_loss_pct=0.01,
        )
        assert result.kelly_fraction <= 0.25

    def test_zero_win_prob_produces_negative_ev(self):
        result = compute_ev(
            win_prob=0.0,
            avg_win_pct=0.02,
            avg_loss_pct=0.01,
        )
        assert result.ev_pct <= 0
        assert result.approved is False

    def test_batch_ev_stamps_approval_flag(self):
        # First candidate: high win rate + good R:R (2.5% win vs 0.8% loss)
        candidates = [
            {"win_rate": 0.65, "avg_profit_pct": 0.025, "avg_loss_pct": 0.008, "historical_sample_size": 20},
            {"win_rate": 0.25, "avg_profit_pct": 0.003, "avg_loss_pct": 0.02, "historical_sample_size": 20},
        ]
        results = batch_evaluate_ev(candidates)
        assert results[0]["ev_approved"] is True
        assert results[1]["ev_approved"] is False
        assert "ev_analysis" in results[0]

    def test_kelly_position_pct_non_negative(self):
        result = compute_ev(
            win_prob=0.50,
            avg_win_pct=0.01,
            avg_loss_pct=0.01,
        )
        assert result.kelly_fraction >= 0.0

    def test_to_dict_has_expected_fields(self):
        result = compute_ev(
            win_prob=0.55, avg_win_pct=0.015, avg_loss_pct=0.01
        )
        d = result.to_dict()
        assert "ev_pct" in d
        assert "kelly_fraction" in d
        assert "rr_ratio" in d
        assert "approved" in d
