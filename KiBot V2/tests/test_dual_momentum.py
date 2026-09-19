import pytest
from council.dual_momentum import DualMomentumEngine

def test_calc_tsm():
    engine = DualMomentumEngine()
    # +10% return
    assert engine.calc_tsm([100.0, 110.0]) == pytest.approx(10.0)
    # -5% return
    assert engine.calc_tsm([100.0, 95.0]) == pytest.approx(-5.0)

def test_calc_max_drawdown():
    engine = DualMomentumEngine()
    # Drops from 100 to 80 = 20% DD
    prices = [100.0, 105.0, 90.0, 80.0, 95.0]
    # Peak is 105, trough is 80 -> (105 - 80) / 105 = 23.8%
    dd = engine.calc_max_drawdown(prices)
    assert dd == pytest.approx(23.8095, rel=1e-3)

def test_dual_momentum_universe_selection():
    engine = DualMomentumEngine(hurdle_rate_pct=0.0, max_drawdown_limit_pct=15.0, top_csm_quantile=0.50)
    universe = {
        # Asset A: Strong gain (+30%), small drawdown (5%) -> PASS & TOP
        "ASSET_A": [100.0, 105.0, 102.0, 130.0],
        # Asset B: Moderate gain (+15%), small drawdown (4%) -> PASS
        "ASSET_B": [100.0, 104.0, 100.0, 115.0],
        # Asset C: Negative return (-10%) -> FAIL TSM
        "ASSET_C": [100.0, 95.0, 90.0],
        # Asset D: Positive return (+10%), but high drawdown (25% > 15%) -> FAIL DD Protection
        "ASSET_D": [100.0, 120.0, 90.0, 110.0],
    }
    res = engine.evaluate_universe(universe)
    assert "ASSET_A" in res["selected_symbols"]
    assert "ASSET_C" not in res["selected_symbols"]
    assert "ASSET_D" not in res["selected_symbols"]
    assert res["ranked_csm"][0][0] == "ASSET_A"
