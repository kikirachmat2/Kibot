import pytest
from pathlib import Path
from council.regime_detector import MarketRegime
from paper_rotation_runner import RotationPaperRunner

@pytest.fixture
def temp_rotation_runner(tmp_path):
    state_file = tmp_path / "paper_p5_test_state.json"
    return RotationPaperRunner(state_file=state_file)

def test_scenario_1_bull_btc_dominant(temp_rotation_runner):
    runner = temp_rotation_runner
    regime_override = {
        "regime": MarketRegime.BULL,
        "btc_dominance_trend_7h": 1.2,
    }
    # Altcoin DOGEIDR should be blocked because focus is BTC/ETH
    alt_cand = {
        "symbol": "DOGEIDR",
        "price": 2000.0,
        "volume_idr": 200_000_000.0,
        "spread_pct": 0.002,
        "volume_ratio": 2.5,
    }
    res_alt = runner.evaluate_candidate(alt_cand, regime_override=regime_override)
    assert res_alt["evaluated"] is False
    assert res_alt["reason"] == "bull_btc_dominant"

    # BTCIDR should be accepted
    btc_cand = {
        "symbol": "BTCIDR",
        "price": 1_000_000_000.0,
        "volume_idr": 500_000_000.0,
        "spread_pct": 0.001,
        "volume_ratio": 1.2,
    }
    res_btc = runner.evaluate_candidate(btc_cand, regime_override=regime_override)
    assert res_btc["evaluated"] is True
    assert "BTCIDR" in runner.ledger.open_positions

def test_scenario_2_bear_risk_off(temp_rotation_runner):
    runner = temp_rotation_runner
    regime_override = {
        "regime": MarketRegime.BEAR,
        "btc_dominance_trend_7h": 0.8,
    }
    # Both BTC and Altcoins must be blocked to hold cash
    cand = {
        "symbol": "BTCIDR",
        "price": 1_000_000_000.0,
        "volume_idr": 500_000_000.0,
        "spread_pct": 0.001,
        "volume_ratio": 3.0,
    }
    res = runner.evaluate_candidate(cand, regime_override=regime_override)
    assert res["evaluated"] is False
    assert res["reason"] == "bear_risk_off"
    assert len(runner.ledger.open_positions) == 0

def test_scenario_3_range_altcoin_rotation(temp_rotation_runner):
    runner = temp_rotation_runner
    regime_override = {
        "regime": MarketRegime.RANGE,
        "btc_dominance_trend_7h": -1.5,
    }
    runner.set_btc_correlation("CORRIDR", 0.85)
    runner.set_btc_correlation("INDEPIDR", 0.45)

    # 1. High correlation altcoin (> 0.70) rejected
    res_corr = runner.evaluate_candidate({
        "symbol": "CORRIDR",
        "price": 1000.0,
        "volume_idr": 150_000_000.0,
        "spread_pct": 0.002,
        "volume_ratio": 2.5,
    }, regime_override=regime_override)
    assert res_corr["evaluated"] is False
    assert res_corr["reason"] == "high_btc_correlation"

    # 2. Low volume altcoin (< 2.0x) rejected
    res_novol = runner.evaluate_candidate({
        "symbol": "INDEPIDR",
        "price": 1000.0,
        "volume_idr": 150_000_000.0,
        "spread_pct": 0.002,
        "volume_ratio": 1.4,
    }, regime_override=regime_override)
    assert res_novol["evaluated"] is False
    assert res_novol["reason"] == "no_volume_anomaly"

    # 3. Independent altcoin with volume anomaly accepted
    res_ok = runner.evaluate_candidate({
        "symbol": "INDEPIDR",
        "price": 1000.0,
        "volume_idr": 150_000_000.0,
        "spread_pct": 0.002,
        "volume_ratio": 2.8,
    }, regime_override=regime_override)
    assert res_ok["evaluated"] is True
    assert "INDEPIDR" in runner.ledger.open_positions

def test_scenario_4_bear_independent_alt_escape(temp_rotation_runner):
    runner = temp_rotation_runner
    regime_override = {
        "regime": MarketRegime.BEAR,
        "btc_dominance_trend_7h": -0.9,
    }
    runner.set_btc_correlation("MODCORRIDR", 0.60)
    runner.set_btc_correlation("TRUEINDEPIDR", 0.30)

    # Correlated (>= 0.50) rejected in Bear market
    res1 = runner.evaluate_candidate({
        "symbol": "MODCORRIDR",
        "price": 500.0,
        "volume_idr": 200_000_000.0,
        "spread_pct": 0.002,
        "volume_ratio": 3.0,
    }, regime_override=regime_override)
    assert res1["evaluated"] is False
    assert res1["reason"] == "bear_correlated_rejection"

    # Truly independent (< 0.50) with volume anomaly accepted
    res2 = runner.evaluate_candidate({
        "symbol": "TRUEINDEPIDR",
        "price": 500.0,
        "volume_idr": 200_000_000.0,
        "spread_pct": 0.002,
        "volume_ratio": 3.0,
    }, regime_override=regime_override)
    assert res2["evaluated"] is True
    assert "TRUEINDEPIDR" in runner.ledger.open_positions
