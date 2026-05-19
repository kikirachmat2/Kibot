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
