import pytest
import asyncio
from pathlib import Path
from Core.Scanner.wave_detection_engine import WaveDetectionEngine
from Core.Scanner.market_wide_wave_scanner import MarketWideWaveScanner
from Core.Web3.pumpfun_fast_scanner import PumpfunFastScanner

def test_wave_detection_engine_classification():
    engine = WaveDetectionEngine()
    
    # 1. New Launch token (must have fresh_pair_creation=True and bonding_curve_progress=0.0)
    token_new = {
        "symbol": "NEWCOIN",
        "price_acceleration": 20.0,
        "volume_acceleration": 15.0,
        "fresh_pair_creation": True,
        "migration_event": False,
        "bonding_curve_progress": 0.0,
        "buy_sell_imbalance": 0.8,
        "liquidity_expansion": 10.0,
        "holder_growth_pct": 15.0,
        "exit_liquidity_quality": 0.9
    }
    res_new = engine.evaluate_token(token_new)
    assert res_new["wave_phase"] == "NEW_LAUNCH"
    assert res_new["decision"] == "APPROVE"

    # 2. Early Pump token (bonding_curve_progress > 0, price_accel > 15, vol_accel > 10)
    token_pump = {
        "symbol": "PUMPCOIN",
        "price_acceleration": 35.0,
        "volume_acceleration": 22.0,
        "fresh_pair_creation": False,
        "migration_event": False,
        "bonding_curve_progress": 60.0,
        "buy_sell_imbalance": 0.78,
        "liquidity_expansion": 12.0,
        "holder_growth_pct": 10.0,
        "exit_liquidity_quality": 0.9
    }
    res_pump = engine.evaluate_token(token_pump)
    assert res_pump["wave_phase"] == "EARLY_PUMP"
    assert res_pump["decision"] == "APPROVE"

    # 3. Unsafe / overextended token (risk_score > 60.0 through no route and imbalance)
    token_unsafe = {
        "symbol": "REJECTCOIN",
        "price_acceleration": 150.0,
        "volume_acceleration": 80.0,
        "fresh_pair_creation": False,
        "migration_event": False,
        "bonding_curve_progress": 99.0,
        "buy_sell_imbalance": 0.1,  # Heavy dumping (+40 risk)
        "route_availability": False, # No route (+50 risk)
        "liquidity_expansion": 0.0,
        "holder_growth_pct": 0.0
    }
    res_unsafe = engine.evaluate_token(token_unsafe)
    assert res_unsafe["wave_phase"] == "UNSAFE"
    assert res_unsafe["decision"] == "REJECT"

@pytest.mark.anyio
async def test_market_wide_wave_scanner_integration():
    scanner = MarketWideWaveScanner()
    state = await scanner.scan()
    
    assert state["scan_mode"] == "MARKET_WIDE"
    assert "sectors_checked" in state
    assert state["candidates_found"] > 0
    assert isinstance(state["best_candidates"], list)
    assert isinstance(state["hot_waves"], list)

@pytest.mark.anyio
async def test_pumpfun_fast_scanner_dual_interface():
    scanner = PumpfunFastScanner()
    
    # Test scan() interface (needed by PumpfunLiveRunner)
    state = await scanner.scan()
    assert state["runner"] == "ACTIVE"
    assert "best_candidate" in state
    assert "candidates" in state
    assert "rejected" in state

    # Test scan_waves() interface
    state_waves = await scanner.scan_waves()
    assert state_waves["runner"] == "ACTIVE"
