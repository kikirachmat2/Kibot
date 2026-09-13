#!/usr/bin/env python3
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# Ensure project root is in the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Core.Intelligence.leadlag_alpha import LeadLagAlphaEngine
from Core.Support.ki_config import KiConfig

@pytest.mark.anyio
async def test_leadlag_alpha_fetch_tickers():
    engine = LeadLagAlphaEngine()
    
    # Mock network responses to ensure test is fully offline and resilient
    mock_binance = {"BTCUSDT": 67000.0, "ETHUSDT": 3400.0}
    mock_indodax = {
        "BTC/IDR": {"last": 1340000000.0, "vol_idr": 60000000.0, "buy": 1339000000.0, "sell": 1341000000.0},
        "ETH/IDR": {"last": 38000000.0, "vol_idr": 45000000.0, "buy": 37900000.0, "sell": 38100000.0}
    }
    
    with patch.object(engine, 'fetch_binance_tickers', return_value=mock_binance), \
         patch.object(engine, 'fetch_indodax_tickers', return_value=mock_indodax):
         
        binance_res = await engine.fetch_binance_tickers()
        indodax_res = await engine.fetch_indodax_tickers()
        
        assert binance_res["BTCUSDT"] == 67000.0
        assert indodax_res["BTC/IDR"]["last"] == 1340000000.0

@pytest.mark.anyio
async def test_leadlag_scout_bullish_lag_signal():
    engine = LeadLagAlphaEngine()
    
    # Configure parameters to make it easy to trigger early lag signal
    engine.min_leader_move_pct = 1.0
    engine.max_follower_move_pct = 0.5
    engine.confidence_floor = 0.5
    engine.min_volume_idr = 10000000.0
    
    # Record lookback state
    # T0 (lookback) prices
    engine._record_price("BTCUSDT", 60000.0)
    engine._record_price("BTC/IDR", 960000000.0)
    
    # T1 (current) prices
    # Leader has moved up from 60000 -> 61200 (+2.0% change)
    # Follower has moved up from 960000000 -> 961920000 (+0.2% change)
    # This represents a massive lag gap of 1.8%
    mock_binance = {"BTCUSDT": 61200.0}
    mock_indodax = {
        "BTC/IDR": {
            "last": 961920000.0,
            "vol_idr": 20000000.0,
            "buy": 961000000.0,
            "sell": 962000000.0
        }
    }
    
    with patch.object(engine, 'fetch_binance_tickers', return_value=mock_binance), \
         patch.object(engine, 'fetch_indodax_tickers', return_value=mock_indodax):
         
        opps = await engine.calculate_opportunities()
        
        btc_opp = next((o for o in opps if o["symbol"] == "BTC/IDR"), None)
        assert btc_opp is not None
        print("\n[BULLISH TEST] BTC/IDR Opportunity Result:")
        print(f"Leader Change: {btc_opp['leader_change_pct']}%")
        print(f"Follower Change: {btc_opp['follower_change_pct']}%")
        print(f"Lag Gap: {btc_opp['lag_gap_pct']}%")
        print(f"Expected Net Yield: {btc_opp['expected_net_pct']}%")
        print(f"Trade Grade: {btc_opp['trade_grade']}")
        print(f"Lifecycle: {btc_opp['lifecycle']}")
        
        assert btc_opp["trade_grade"] in ["A", "B"]
        assert btc_opp["lifecycle"] == "EARLY_LAG"

@pytest.mark.anyio
async def test_leadlag_rejection_gates():
    engine = LeadLagAlphaEngine()
    
    # Configure gates
    engine.min_leader_move_pct = 1.0
    engine.max_spread_pct = 0.5
    engine.min_volume_idr = 50000000.0
    
    # 1. Reject due to no leader movement
    engine._record_price("BTCUSDT", 60000.0)
    engine._record_price("BTC/IDR", 960000000.0)
    
    mock_binance_no_move = {"BTCUSDT": 60060.0}  # +0.1% change
    mock_indodax = {
        "BTC/IDR": {
            "last": 960000000.0,
            "vol_idr": 100000000.0,
            "buy": 959000000.0,
            "sell": 961000000.0
        }
    }
    
    with patch.object(engine, 'fetch_binance_tickers', return_value=mock_binance_no_move), \
         patch.object(engine, 'fetch_indodax_tickers', return_value=mock_indodax):
         
        opps = await engine.calculate_opportunities()
        btc_opp = next((o for o in opps if o["symbol"] == "BTC/IDR"), None)
        assert btc_opp is not None
        assert btc_opp["trade_grade"] == "REJECT"
        assert any("Leader move too small" in r for r in btc_opp["reasons"])

    # 2. Reject due to volume floor
    mock_binance_good_move = {"BTCUSDT": 61200.0} # +2.0% change
    mock_indodax_low_vol = {
        "BTC/IDR": {
            "last": 960000000.0,
            "vol_idr": 1000000.0, # 1 Million IDR volume (low!)
            "buy": 959000000.0,
            "sell": 961000000.0
        }
    }
    
    with patch.object(engine, 'fetch_binance_tickers', return_value=mock_binance_good_move), \
         patch.object(engine, 'fetch_indodax_tickers', return_value=mock_indodax_low_vol):
         
        opps = await engine.calculate_opportunities()
        btc_opp = next((o for o in opps if o["symbol"] == "BTC/IDR"), None)
        assert btc_opp is not None
        assert btc_opp["trade_grade"] == "REJECT"
        assert any("volume too low" in r for r in btc_opp["reasons"])
