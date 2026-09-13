import pytest
from Core.Support.ki_config import KiConfig
from Core.Intelligence.expected_value import compute_ev, ev_from_candidate
from Core.Intelligence.paper_trade_tracker import DEFAULT_FEE_PCT, DEFAULT_SLIPPAGE_PCT
from Core.Intelligence.exit_plan import FEE_ROUNDTRIP_PCT
from Core.Intelligence.indodax_microstructure import IndodaxMicrostructureAnalyzer
from Core.Intelligence.kibot_learning_engine import MAKER_FEE, TAKER_FEE
from Core.Executors.Indodax.indodax_executor import DEFAULT_FEE_ROUNDTRIP_PCT


def test_fee_ssot_constants():
    """Verify that official Indodax fee constants in KiConfig match official rates."""
    assert round(KiConfig.INDODAX_TAKER_BUY_FEE_PCT, 4) == 0.0031
    assert round(KiConfig.INDODAX_TAKER_SELL_FEE_PCT, 4) == 0.0030
    assert round(KiConfig.INDODAX_MAKER_BUY_FEE_PCT, 4) == 0.0021
    assert round(KiConfig.INDODAX_MAKER_SELL_FEE_PCT, 4) == 0.0020

    assert round(KiConfig.KIBOT_TAKER_FEE_ROUNDTRIP_PCT, 4) == 0.0061
    assert round(KiConfig.KIBOT_MAKER_FEE_ROUNDTRIP_PCT, 4) == 0.0041
    assert round(KiConfig.KIBOT_DEFAULT_SLIPPAGE_PCT, 4) == 0.0010


def test_fee_ssot_module_integration():
    """Verify that all Core modules reference KiConfig SSOT fee constants."""
    assert DEFAULT_FEE_PCT == KiConfig.KIBOT_TAKER_FEE_ROUNDTRIP_PCT
    assert DEFAULT_SLIPPAGE_PCT == KiConfig.KIBOT_DEFAULT_SLIPPAGE_PCT
    assert FEE_ROUNDTRIP_PCT == KiConfig.KIBOT_TAKER_FEE_ROUNDTRIP_PCT
    assert round(DEFAULT_FEE_ROUNDTRIP_PCT, 2) == 0.61
    assert MAKER_FEE == KiConfig.INDODAX_MAKER_BUY_FEE_PCT
    assert TAKER_FEE == KiConfig.INDODAX_TAKER_BUY_FEE_PCT

    analyzer = IndodaxMicrostructureAnalyzer()
    assert abs(analyzer.taker_fee_pct - KiConfig.INDODAX_TAKER_BUY_FEE_PCT) < 1e-6


def test_ev_computation_uses_ssot_fee():
    """Verify compute_ev with KiConfig SSOT fee and slippage."""
    res = compute_ev(
        win_prob=0.60,
        avg_win_pct=0.035,
        avg_loss_pct=0.010,
        fee_pct=KiConfig.KIBOT_TAKER_FEE_ROUNDTRIP_PCT,
        slippage_pct=KiConfig.KIBOT_DEFAULT_SLIPPAGE_PCT
    )
    # Friction = 0.0061 (0.61%) + 0.0010 (0.10%) = 0.0071 (0.71%)
    # Net win = 0.035 - 0.0071 = 0.0279 (2.79%)
    # Net loss = 0.010 + 0.0071 = 0.0171 (1.71%)
    # Net R:R = 0.0279 / 0.0171 = 1.6316 (>= 1.50)
    assert res.approved is True
    assert round(res.ev_pct, 4) == 0.0099
