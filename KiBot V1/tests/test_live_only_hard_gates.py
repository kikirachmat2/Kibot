from Core.Intelligence.expected_value import ev_from_candidate
from Core.Intelligence.strategy_scorecard import score_candidate, ScorecardVerdict
from Core.Trading.autonomous_sizing import AutonomousSizing
from Core.Support.runtime_mode_guard import normalize_runtime_mode, LIVE_ONLY


def test_ev_missing_history_rejected():
    result = ev_from_candidate({"win_rate": 0.9, "avg_profit_pct": 0.03, "avg_loss_pct": 0.01, "historical_sample_size": 3})
    assert result.approved is False
    assert any("sample size" in r.lower() for r in result.rejection_reasons)


def test_scorecard_cannot_approve_without_ev():
    result = score_candidate(
        signal_quality_dict={"grade": "STRONG"},
        ev_analysis_dict={"approved": False, "ev_pct": 0.8},
        market_regime="BULL",
        llm_advisory_score=1.0,
    )
    assert result.verdict in {ScorecardVerdict.REJECTED, ScorecardVerdict.PAPER_ONLY}
    assert "hard_reject_ev_not_approved" in result.breakdown


def test_aggressive_probe_disabled_by_default():
    sizing = AutonomousSizing()
    result = sizing.size(
        total_capital_idr=100000,
        venue_capital_idr=100000,
        route_bucket_idr=100000,
        available_balance_idr=100000,
        daily_risk_remaining_idr=1000,
        liquidity_usd=100000,
        slippage_pct=0.2,
        confidence=0.9,
        ev_pct=0.1,
        volatility_pct=2.0,
        current_open_exposure_idr=0,
        exit_available=True,
        route="indodax",
        reserve_locked=True,
        momentum_score=0.9,
        exit_quality="A",
        trade_grade="A",
        stop_loss_pct=1.5,
        route_min_trade_idr=10000,
    )
    assert result["approved"] is False or float(result["size_idr"]) <= 10000


def test_runtime_mode_normalizes_legacy_to_live_only():
    assert normalize_runtime_mode("controlled-live") == LIVE_ONLY
    assert normalize_runtime_mode("paper") == LIVE_ONLY

