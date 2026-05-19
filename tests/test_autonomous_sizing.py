from Core.Trading.autonomous_sizing import AutonomousSizing


def test_autonomous_sizing_approves_reasonable_trade():
    sizing = AutonomousSizing()
    res = sizing.size(
        total_capital_idr=1_000_000,
        venue_capital_idr=1_000_000,
        route_bucket_idr=250_000,
        available_balance_idr=1_000_000,
        daily_risk_remaining_idr=50_000,
        liquidity_usd=50_000,
        slippage_pct=0.5,
        confidence=0.85,
        ev_pct=4.0,
        volatility_pct=8.0,
        current_open_exposure_idr=0,
        exit_available=True,
        route="indodax",
        reserve_locked=True,
        hard_cap_idr=0,
        liquidity_safe_size_idr=200_000,
    )
    assert res["approved"] is True
    assert res["size_idr"] > 0


def test_autonomous_sizing_rejects_when_no_exit():
    sizing = AutonomousSizing()
    res = sizing.size(
        total_capital_idr=100_000,
        venue_capital_idr=100_000,
        route_bucket_idr=50_000,
        available_balance_idr=100_000,
        daily_risk_remaining_idr=1_500,
        liquidity_usd=50_000,
        slippage_pct=0.5,
        confidence=0.85,
        ev_pct=4.0,
        volatility_pct=8.0,
        current_open_exposure_idr=0,
        exit_available=False,
        route="indodax",
        reserve_locked=True,
        hard_cap_idr=0,
        liquidity_safe_size_idr=80_000,
    )
    assert res["approved"] is False
    assert res["reason"] == "exit_unavailable"
    assert res["guard_layer"] == "HARD_BLOCK"


def test_autonomous_sizing_uses_stop_loss_risk_not_notional_cap():
    sizing = AutonomousSizing()
    res = sizing.size(
        total_capital_idr=184_000,
        venue_capital_idr=100_000,
        route_bucket_idr=70_000,
        available_balance_idr=70_000,
        daily_risk_remaining_idr=2_700,
        liquidity_usd=25_000,
        slippage_pct=0.4,
        confidence=0.88,
        ev_pct=1.2,
        volatility_pct=6.0,
        current_open_exposure_idr=0,
        exit_available=True,
        route="indodax",
        reserve_locked=True,
        hard_cap_idr=0,
        liquidity_safe_size_idr=60_000,
        stop_loss_pct=1.5,
        route_min_trade_idr=10_000,
    )
    assert res["approved"] is True
    assert res["size_idr"] >= 10_000
    assert res["max_loss_if_stop_hit_idr"] <= 2_700


def test_autonomous_sizing_probe_lifts_to_min_trade_for_strong_momentum(monkeypatch):
    monkeypatch.setenv("KIBOT_PROBE_MIN_CONFIDENCE", "0.78")
    monkeypatch.setenv("KIBOT_PROBE_MIN_MOMENTUM", "0.70")
    sizing = AutonomousSizing()
    res = sizing.size(
        total_capital_idr=100_000,
        venue_capital_idr=100_000,
        route_bucket_idr=30_000,
        available_balance_idr=30_000,
        daily_risk_remaining_idr=1_500,
        liquidity_usd=8_000,
        slippage_pct=1.0,
        confidence=0.86,
        ev_pct=-0.1,
        volatility_pct=20.0,
        current_open_exposure_idr=0,
        exit_available=True,
        route="indodax",
        reserve_locked=True,
        hard_cap_idr=0,
        liquidity_safe_size_idr=20_000,
        momentum_score=0.85,
        exit_quality="A",
        stop_loss_pct=1.5,
        route_min_trade_idr=10_000,
    )
    assert res["approved"] is True
    assert res["reason"] == "aggressive_probe"
    assert res["guard_action"] == "PROBE_APPROVED"
    assert "ev_not_positive" in res["guard_reasons"]
