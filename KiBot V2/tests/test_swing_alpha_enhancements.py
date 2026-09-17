import pytest
import time

from council.swing_evaluator import SwingEvaluator
from council.indicators import calc_choppiness_index, calc_volume_zscore, calc_bollinger_pct_b
from ingestion.binance_tracker import BinanceLeadLagTracker


def test_choppiness_index_rejection():
    """
    Validates that Trend-Following rejects buys when Choppiness Index >= 61.8 (whipsaw / consolidation).
    """
    evaluator = SwingEvaluator()
    base_candidate = {
        "symbol": "BTC/IDR",
        "price": 1_000_000_000.0,
        "spread_pct": 0.001,
        "ema20": 1_020_000_000.0,
        "ema50": 980_000_000.0,
        "ema100": 920_000_000.0,
        "rsi14": 55.0,
        "atr14": 35_000_000.0,
        "volume": 150.0,
        "volume_sma20": 120.0,
    }

    # 1. High Choppiness (CI = 65.0 >= 61.8) -> REJECT
    cand_choppy = dict(base_candidate)
    cand_choppy["choppiness_index"] = 65.0
    dec_choppy = evaluator.evaluate(cand_choppy)
    assert dec_choppy.verdict == "REJECTED"

    # 2. Strong Trend (CI = 35.0 < 61.8) -> APPROVE
    cand_trend = dict(base_candidate)
    cand_trend["choppiness_index"] = 35.0
    dec_trend = evaluator.evaluate(cand_trend)
    assert dec_trend.verdict == "APPROVED"
    assert dec_trend.strategy == "TREND_FOLLOWING"


def test_anti_blowoff_rsi_upper_cap():
    """
    Validates that Trend-Following rejects buys when RSI > 72.0 (blow-off top FOMO peak).
    """
    evaluator = SwingEvaluator()
    candidate = {
        "symbol": "BTC/IDR",
        "price": 1_000_000_000.0,
        "spread_pct": 0.001,
        "ema20": 1_020_000_000.0,
        "ema50": 980_000_000.0,
        "ema100": 920_000_000.0,
        "rsi14": 78.5, # Overbought > 72.0
        "atr14": 35_000_000.0,
        "volume": 150.0,
        "volume_sma20": 120.0,
        "choppiness_index": 45.0,
    }
    decision = evaluator.evaluate(candidate)
    assert decision.verdict == "REJECTED"


def test_volatility_parity_sizing():
    """
    Validates Volatility Risk Parity formula:
    Position Size = min((Bankroll * Risk_Target) / (SL_pct / 100), Bankroll * Max_Cap_pct)
    Both positions target ~2.0% dollar risk on bankroll (Rp 200,000 on Rp 10M bankroll).
    """
    evaluator = SwingEvaluator(target_risk_pct=0.02, max_cap_pct=0.35)
    bankroll = 10_000_000.0

    # Case 1: Low-volatility instrument (SL = 3.5%)
    # Raw size = (10M * 0.02) / 0.035 = Rp 5,714,285 -> Capped at 35% = Rp 3,500,000
    size_btc = evaluator.calculate_position_size(bankroll, sl_pct=3.5)
    assert size_btc == 3_500_000.0

    # Case 2: High-volatility instrument (SL = 7.0%)
    # Raw size = (10M * 0.02) / 0.070 = Rp 2,857,142.86 -> Below 35% cap
    size_avax = evaluator.calculate_position_size(bankroll, sl_pct=7.0)
    assert size_avax == 2_857_142.86

    # Verify Equal Dollar Risk:
    # Dollar risk on AVAX = 2,857,142.86 * 0.07 = Rp 200,000 (Exactly 2.0% of bankroll!)
    dollar_risk_avax = size_avax * 0.07
    assert dollar_risk_avax == pytest.approx(200_000.0, rel=1e-3)


def test_binance_lead_lag_dump_rejection():
    """
    Validates that a buy signal on Indodax is blocked if Binance leading momentum is dumping.
    """
    evaluator = SwingEvaluator()
    base_cand = {
        "symbol": "BTC/IDR",
        "price": 1_000_000_000.0,
        "spread_pct": 0.001,
        "ema20": 1_020_000_000.0,
        "ema50": 980_000_000.0,
        "ema100": 920_000_000.0,
        "rsi14": 55.0,
        "atr14": 35_000_000.0,
        "volume": 150.0,
        "volume_sma20": 120.0,
        "choppiness_index": 42.0,
    }

    # Case 1: Binance dumping -2.0% in 1h -> REJECT
    cand_dumping = dict(base_cand)
    cand_dumping["binance_momentum_1h"] = -0.020 # -2.0% < -1.5%
    dec_dump = evaluator.evaluate(cand_dumping)
    assert dec_dump.verdict == "REJECTED"

    # Case 2: Binance dumping flag is True -> REJECT
    cand_dump_flag = dict(base_cand)
    cand_dump_flag["binance_is_dumping"] = True
    dec_flag = evaluator.evaluate(cand_dump_flag)
    assert dec_flag.verdict == "REJECTED"

    # Case 3: Binance healthy (+0.8%) -> APPROVE
    cand_ok = dict(base_cand)
    cand_ok["binance_momentum_1h"] = 0.008
    cand_ok["binance_is_dumping"] = False
    dec_ok = evaluator.evaluate(cand_ok)
    assert dec_ok.verdict == "APPROVED"


def test_binance_tracker_momentum_calculation():
    """
    Validates BinanceLeadLagTracker:
    - Accurate 5m, 1h, and 24h rolling return calculations.
    - Automatic eviction of stale ticks > 3600s.
    - Dump detection trigger.
    """
    tracker = BinanceLeadLagTracker(max_history_s=3600.0)
    now = time.time()

    # Feed 1 hour of price progression:
    # 1h ago: price = 60,000
    # 5m ago: price = 59,500
    # now:    price = 58,000 (dumping!)
    tracker.update_ticker({"symbol": "BTCUSDT", "close": 60_000.0, "open": 59_000.0, "ts": now - 3500})
    tracker.update_ticker({"symbol": "BTCUSDT", "close": 59_500.0, "open": 59_000.0, "ts": now - 280})
    tracker.update_ticker({"symbol": "BTCUSDT", "close": 58_000.0, "open": 59_000.0, "ts": now})

    mom = tracker.get_momentum("BTCUSDT")
    # 1h return = (58,000 - 60,000) / 60,000 = -3.33%
    assert mom["return_1h"] == pytest.approx(-0.0333, abs=1e-3)
    # 5m return = (58,000 - 59,500) / 59,500 = -2.52%
    assert mom["return_5m"] == pytest.approx(-0.0252, abs=1e-3)
    # 24h return = (58,000 - 59,000) / 59,000 = -1.69%
    assert mom["return_24h"] == pytest.approx(-0.0169, abs=1e-3)

    # Verify dump detection
    is_dump, reason = tracker.is_dumping("BTCUSDT")
    assert is_dump is True
    assert "dump" in reason.lower()


def test_mean_reversion_bollinger_pct_b():
    """
    Validates that Mean-Reversion approves when Bollinger %B <= 0.05
    and blocks if Binance catastrophic dump is detected (<-4.0%).
    """
    evaluator = SwingEvaluator()
    candidate = {
        "symbol": "AVAX/IDR",
        "price": 380_000.0,
        "spread_pct": 0.002,
        "lower_bb": 390_000.0,
        "middle_bb": 420_000.0,
        "adx14": 18.5,
        "rsi14": 38.0,
        "sma20_slope": 0.005,
        "atr14": 15_000.0,
        "bollinger_pct_b": 0.02, # <= 0.05 (Deep oversold)
        "binance_momentum_1h": -0.01, # -1.0% normal pullback
    }
    decision = evaluator.evaluate(candidate)
    assert decision.verdict == "APPROVED"
    assert decision.strategy == "MEAN_REVERSION"

    # Case 2: Catastrophic crash (-5.0% in 1h on Binance) -> Falling knife guard
    cand_crash = dict(candidate)
    cand_crash["binance_momentum_1h"] = -0.050
    dec_crash = evaluator.evaluate(cand_crash)
    assert dec_crash.verdict == "REJECTED"
