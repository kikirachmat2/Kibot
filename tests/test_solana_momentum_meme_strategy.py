from Core.Intelligence.strategy.solana_momentum_meme_strategy import SolanaMomentumMemeStrategy


def test_meme_strategy_rejects_low_liquidity():
    strategy = SolanaMomentumMemeStrategy()
    result = strategy.evaluate_candidate({
        "symbol": "DEGEN",
        "liquidity_usd": 500,
        "volume_1h_usd": 100,
        "change_24h_pct": 200,
        "change_5m_pct": 25,
        "change_1h_pct": 50,
        "safety_score": 80,
        "holders": 100,
        "age_minutes": 20,
    })
    assert result["decision"] == "REJECT"
    assert "liquidity_too_thin" in result["reason"]


def test_meme_strategy_approves_small_size():
    strategy = SolanaMomentumMemeStrategy()
    result = strategy.evaluate_candidate({
        "symbol": "USRX",
        "liquidity_usd": 50000,
        "volume_1h_usd": 12000,
        "volume_5m_usd": 3000,
        "change_24h_pct": 90,
        "change_5m_pct": 18,
        "change_1h_pct": 40,
        "safety_score": 85,
        "holders": 150,
        "age_minutes": 60,
    })
    assert result["decision"] == "APPROVE"
    assert result["max_trade_idr"] > 0
    assert result["exit_plan_required"] is True

