import pytest
from council.swing_evaluator import SwingEvaluator, normalize_symbol
from council.evaluator import CouncilDecision

def test_normalize_symbol():
    assert normalize_symbol("btc/idr") == "BTCIDR"
    assert normalize_symbol("eth_idr") == "ETHIDR"
    assert normalize_symbol("avaxidr") == "AVAXIDR"

def test_swing_ineligible_symbol():
    evaluator = SwingEvaluator()
    candidate = {"symbol": "DOGE/IDR", "price": 2500.0}
    decision = evaluator.evaluate(candidate)
    assert decision.verdict == "REJECTED"
    assert "not in swing universe" in decision.reason

def test_swing_high_spread_rejection():
    evaluator = SwingEvaluator()
    candidate = {
        "symbol": "BTC/IDR",
        "price": 1_000_000_000.0,
        "spread_pct": 0.01, # 1.0% > 0.80% limit
        "ema20": 1_050_000_000.0,
        "ema50": 1_000_000_000.0,
        "ema100": 950_000_000.0,
        "rsi14": 55.0,
        "volume": 100.0,
        "volume_sma20": 90.0,
        "binance_data_status": "OK",  # D-08: must pass Binance guard to reach spread check
    }
    decision = evaluator.evaluate(candidate)
    assert decision.verdict == "REJECTED"
    assert "exceeds swing limit" in decision.reason

def test_btc_trend_following_approval():
    evaluator = SwingEvaluator()
    candidate = {
        "symbol": "BTC/IDR",
        "price": 1_050_000_000.0,
        "spread_pct": 0.001,
        "ema20": 1_020_000_000.0,
        "ema50": 980_000_000.0,
        "ema100": 920_000_000.0,
        "rsi14": 58.0,
        "atr14": 35_000_000.0, # 3.33%
        "volume": 150.0,
        "volume_sma20": 120.0,
        "binance_data_status": "OK",  # D-08: fresh Binance data
    }
    decision = evaluator.evaluate(candidate, bankroll_idr=12_000_000.0)
    assert decision.verdict == "APPROVED"
    assert decision.action == "BUY"
    assert decision.strategy == "TREND_FOLLOWING"
    assert decision.enrichment_status == "1D_SWING_TF"
    assert decision.max_hold_time_s == 21 * 86400
    # TP: 2.5 * ATR / price = 2.5 * 35M / 1050M = 8.33%
    # SL: 1.5 * ATR / price = 1.5 * 35M / 1050M = 5.0%
    assert 8.0 <= decision.target_tp_pct <= 8.5
    assert 4.8 <= decision.target_sl_pct <= 5.2
    assert decision.suggested_size_idr == pytest.approx(3_000_000.0, rel=1e-2)

def test_btc_trend_following_rejection_on_rsi():
    evaluator = SwingEvaluator()
    candidate = {
        "symbol": "BTC/IDR",
        "price": 1_050_000_000.0,
        "spread_pct": 0.001,
        "ema20": 1_020_000_000.0,
        "ema50": 980_000_000.0,
        "ema100": 920_000_000.0,
        "rsi14": 46.0, # < 48.0
        "volume": 150.0,
        "volume_sma20": 120.0,
    }
    decision = evaluator.evaluate(candidate)
    assert decision.verdict == "REJECTED"

def test_avax_mean_reversion_approval():
    evaluator = SwingEvaluator()
    candidate = {
        "symbol": "AVAX/IDR",
        "price": 380_000.0,
        "spread_pct": 0.002,
        "lower_bb": 390_000.0, # price <= lower_bb
        "middle_bb": 420_000.0,
        "adx14": 18.5, # <= 25
        "rsi14": 38.0, # <= 45
        "sma20_slope": 0.005, # <= 0.02
        "atr14": 15_000.0,
        "binance_data_status": "OK",  # D-08: fresh Binance data
    }
    decision = evaluator.evaluate(candidate, bankroll_idr=15_000_000.0)
    assert decision.verdict == "APPROVED"
    assert decision.strategy == "MEAN_REVERSION"
    assert decision.enrichment_status == "1D_SWING_MR"
    assert decision.max_hold_time_s == 10 * 86400
    # TP: (middle_bb - price) / price = (420k - 380k) / 380k = 10.53%
    assert 10.0 <= decision.target_tp_pct <= 11.0
    assert decision.suggested_size_idr == pytest.approx(3_750_000.0, rel=1e-2)

def test_avax_mean_reversion_rejection_on_adx():
    evaluator = SwingEvaluator()
    candidate = {
        "symbol": "AVAX/IDR",
        "price": 380_000.0,
        "spread_pct": 0.002,
        "lower_bb": 390_000.0,
        "middle_bb": 420_000.0,
        "adx14": 28.0, # > 25 (trending strongly, mean reversion not safe)
        "rsi14": 38.0,
        "sma20_slope": 0.005,
    }
    decision = evaluator.evaluate(candidate)
    assert decision.verdict == "REJECTED"

def test_eth_mutual_exclusivity():
    evaluator = SwingEvaluator()
    
    # 1. Bullish scenario -> TF approved, MR rejected
    bullish_eth = {
        "symbol": "ETH/IDR",
        "price": 45_000_000.0,
        "spread_pct": 0.001,
        "ema20": 44_000_000.0,
        "ema50": 42_000_000.0,
        "ema100": 40_000_000.0,
        "rsi14": 56.0,
        "volume": 500.0,
        "volume_sma20": 400.0,
        "lower_bb": 41_000_000.0,
        "middle_bb": 44_000_000.0,
        "adx14": 22.0,
        "sma20_slope": 0.01,
        "binance_data_status": "OK",  # D-08: fresh Binance data
    }
    dec_bull = evaluator.evaluate(bullish_eth)
    assert dec_bull.verdict == "APPROVED"
    assert dec_bull.strategy == "TREND_FOLLOWING"

    # 2. Oversold dip scenario -> MR approved, TF rejected
    dip_eth = {
        "symbol": "ETH/IDR",
        "price": 39_500_000.0,
        "spread_pct": 0.001,
        "ema20": 41_000_000.0,
        "ema50": 40_000_000.0,
        "ema100": 39_000_000.0,
        "rsi14": 38.0, # <= 45 -> fails TF (needs >= 48)
        "volume": 500.0,
        "volume_sma20": 400.0,
        "lower_bb": 40_000_000.0, # price <= lower_bb
        "middle_bb": 42_000_000.0,
        "adx14": 20.0,
        "sma20_slope": 0.008,
        "binance_data_status": "OK",  # D-08: fresh Binance data
    }
    dec_dip = evaluator.evaluate(dip_eth)
    assert dec_dip.verdict == "APPROVED"
    assert dec_dip.strategy == "MEAN_REVERSION"

    # 3. Deadband scenario (RSI = 46.5) -> Neither TF nor MR triggers
    deadband_eth = dict(dip_eth)
    deadband_eth["rsi14"] = 46.5
    dec_dead = evaluator.evaluate(deadband_eth)
    assert dec_dead.verdict == "REJECTED"
