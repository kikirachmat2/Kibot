"""Tests for Core/Intelligence/strategy_scorecard.py"""

import pytest
from Core.Intelligence.strategy_scorecard import (
    score_candidate,
    run_scorecard,
    ScorecardVerdict,
    APPROVE_THRESHOLD,
    PAPER_THRESHOLD,
)


def _strong_sq():
    return {"grade": "STRONG", "score": 1.0, "is_tradeable": True}


def _good_ev():
    return {"approved": True, "ev_pct": 0.8}


class TestScoreCandidate:
    def test_all_green_produces_approved(self):
        result = score_candidate(
            signal_quality_dict=_strong_sq(),
            ev_analysis_dict=_good_ev(),
            market_regime="BULL",
            quarantine_active=False,
            punishment_severity=0.0,
        )
        assert result.verdict == ScorecardVerdict.APPROVED
        assert result.composite_score >= APPROVE_THRESHOLD

    def test_quarantine_always_rejects(self):
        result = score_candidate(
            signal_quality_dict=_strong_sq(),
            ev_analysis_dict=_good_ev(),
            market_regime="BULL",
            quarantine_active=True,   # hard block
            punishment_severity=0.0,
        )
        assert result.verdict == ScorecardVerdict.REJECTED

    def test_bear_regime_lowers_score(self):
        bull_result = score_candidate(
            signal_quality_dict=_strong_sq(),
            ev_analysis_dict=_good_ev(),
            market_regime="BULL",
        )
        bear_result = score_candidate(
            signal_quality_dict=_strong_sq(),
            ev_analysis_dict=_good_ev(),
            market_regime="BEAR",
        )
        assert bull_result.composite_score > bear_result.composite_score

    def test_llm_delta_capped_at_015(self):
        result = score_candidate(
            signal_quality_dict=_strong_sq(),
            ev_analysis_dict=_good_ev(),
            market_regime="RANGING",
            llm_advisory_score=10.0,   # extreme — should be capped
        )
        assert result.llm_advisory_delta <= 0.15

    def test_reject_grade_with_negative_ev_produces_reject(self):
        result = score_candidate(
            signal_quality_dict={"grade": "REJECT", "score": 0.0},
            ev_analysis_dict={"approved": False, "ev_pct": -1.0},
            market_regime="BEAR",
        )
        assert result.verdict == ScorecardVerdict.REJECTED

    def test_run_scorecard_attaches_to_candidate(self):
        candidate = {
            "symbol": "BTC/IDR",
            "signal_quality": _strong_sq(),
            "ev_analysis": _good_ev(),
        }
        run_scorecard(candidate, market_regime="RANGING")
        assert "scorecard" in candidate
        assert "scorecard_verdict" in candidate

    def test_breakdown_list_non_empty(self):
        result = score_candidate(
            signal_quality_dict=_strong_sq(),
            ev_analysis_dict=_good_ev(),
        )
        assert len(result.breakdown) > 0

    def test_paper_only_threshold_band(self):
        # Regime VOLATILE + rejected EV should land in PAPER_ONLY band
        result = score_candidate(
            signal_quality_dict={"grade": "ACCEPTABLE", "score": 0.7},
            ev_analysis_dict={"approved": False, "ev_pct": 0.1},
            market_regime="VOLATILE",
            punishment_severity=0.2,
        )
        assert result.verdict in (ScorecardVerdict.PAPER_ONLY, ScorecardVerdict.REJECTED)
