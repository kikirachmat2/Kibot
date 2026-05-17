#!/usr/bin/env python3
"""
KiBot Hardening Verification Suite
==================================
Tests and verifies the core safety invariants of the KiBot system:
1. RiskGate hard drawdown limits (exactly 1.5% MAX_DAILY_LOSS).
2. PhantomRouter execution gate (prevents real transactions in non-live environments).
3. AISearchService loop safety and exception resilience (type-safe fallbacks).
"""

import os
import sys
import asyncio
import logging
import pytest
from unittest.mock import patch, MagicMock

# Ensure project root is in the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Core.risk_gate import RiskGate
from Core.Support.ki_config import KiConfig
from Core.Exchange.phantom_router import PhantomRouter
from Core.Intelligence.kibot_ai_search import AISearchService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("HardenVerify")


def test_riskgate_drawdown_lock():
    print("\n=========================================")
    print("[TEST 1/3] RiskGate Maximum Drawdown Lock")
    print("=========================================")
    
    # 1. Verify constant value in KiConfig
    print(f"KiConfig.MAX_DAILY_LOSS_PERCENT: {KiConfig.MAX_DAILY_LOSS_PERCENT}%")
    assert KiConfig.MAX_DAILY_LOSS_PERCENT == 1.5, "KiConfig.MAX_DAILY_LOSS_PERCENT must be exactly 1.5%"
    
    # 2. Attempt to construct a RiskGate with a high limit (e.g. 5.0%)
    custom_config = {"max_daily_loss_pct": 5.0}
    gate = RiskGate(custom_config)
    
    # 3. Assert it is overridden back to the hard cap
    actual_cap = gate.config.get("max_daily_loss_pct")
    print(f"Constructed RiskGate with custom 5.0% cap. Actual cap resolved: {actual_cap}%")
    assert actual_cap == 1.5, "RiskGate failed to override custom cap to hard lock!"
    print("SUCCESS: RiskGate drawdown locked at 1.5% maximum daily loss.")


@pytest.mark.anyio
async def test_phantom_live_trading_gate():
    print("\n=========================================")
    print("[TEST 2/3] PhantomRouter Live Trading Gate")
    print("=========================================")
    
    # Verify live trading status from config
    print(f"KiConfig.LIVE_TRADING_ENABLED: {KiConfig.LIVE_TRADING_ENABLED}")
    
    # Force LIVE_TRADING_ENABLED to False for the test scope
    with patch.object(KiConfig, 'LIVE_TRADING_ENABLED', False):
        router = PhantomRouter()
        
        # Test swap_assets
        print("Testing swap_assets (live_trading_enabled = False)...")
        swap_res = await router.swap_assets("SOL", "USDC", 1.0, chain="solana")
        print(f"swap_assets result: {swap_res}")
        assert swap_res is True, "swap_assets should return True (simulated success) when live trading is disabled"
        
        # Test snipe_meme_coin
        print("Testing snipe_meme_coin (live_trading_enabled = False)...")
        snipe_res = await router.snipe_meme_coin("PumpCoin", 0.5)
        print(f"snipe_meme_coin result: {snipe_res}")
        assert snipe_res is True, "snipe_meme_coin should return True (simulated success) when live trading is disabled"
        
        # Test execute_mev_arbitrage
        print("Testing execute_mev_arbitrage (live_trading_enabled = False)...")
        mev_res = await router.execute_mev_arbitrage("SOL", "raydium", "jupiter")
        print(f"execute_mev_arbitrage result: {mev_res}")
        assert mev_res is True, "execute_mev_arbitrage should return True (simulated success) when live trading is disabled"
        
    print("SUCCESS: PhantomRouter on-chain operations correctly gated and simulated.")


@pytest.mark.anyio
async def test_search_service_resilience():
    print("\n=========================================")
    print("[TEST 3/3] AISearchService Safe Fallbacks")
    print("=========================================")
    
    from pathlib import Path
    cache_file = Path("state/ai_search_cache.json")
    if cache_file.exists():
        try:
            cache_file.unlink()
        except:
            pass
            
    service = AISearchService()
    
    # 1. Test standard DDG search loop with synthetic failure
    print("Simulating DuckDuckGo search exception handler...")
    with patch("ddgs.DDGS") as mock_ddgs:
        # Force the mock DDGS to raise an exception when text() is called
        mock_instance = MagicMock()
        mock_instance.text.side_effect = Exception("Synthetic DDG Rate Limit / Network Down")
        mock_ddgs.return_value.__enter__.return_value = mock_instance
        
        # Call ddg_search_async which now wraps ddgs inside an asyncio.to_thread loop
        ddg_results = await service.ddg_search_async("bitcoin_failure_test_query", max_results=3)
        print(f"DDG results under failure: {ddg_results} (Type: {type(ddg_results).__name__})")
        assert ddg_results == [], "ddg_search_async must return [] on exceptions"
        
    # 2. Test standard Jina search failure
    print("Simulating Jina search failure fallback...")
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.side_effect = Exception("Network Connection Timed Out")
        
        jina_result = await service.jina_search_async("ethereum")
        print(f"Jina result under failure: '{jina_result}' (Type: {type(jina_result).__name__})")
        assert jina_result == "", "jina_search_async must return '' on exceptions"
        
    # 3. Test Tavily empty fallback
    print("Simulating Tavily search API key omission...")
    with patch.dict(os.environ, {}, clear=True):
        tavily_res = await service.tavily_search_async("solana")
        print(f"Tavily result without API Key: {tavily_res} (Type: {type(tavily_res).__name__})")
        assert tavily_res == {}, "tavily_search_async must return {} if no API key exists"

    print("SUCCESS: AISearchService safely recovered from exceptions with robust type-safe values.")


@pytest.mark.anyio
async def test_bridge_router_hardening():
    print("\n=========================================")
    print("[TEST 4/4] BridgeRouter Hardening & States")
    print("=========================================")
    
    from Core.Exchange.bridge_router import BridgeRouter
    
    mock_phantom = MagicMock()
    mock_indodax = MagicMock()
    
    # Configure mock Indodax to return a high ticket rate or dynamic approximate rate
    async def mock_get_ticker(*args, **kwargs):
        return {"last": 16000}
    mock_indodax.get_ticker = mock_get_ticker
    
    router = BridgeRouter(mock_phantom, mock_indodax)
    
    # 1. Test unprofitable bridge (fee > expected profit)
    # Expected yield in 1 month: 10,000 * 0.05 / 12 = 41.6 IDR
    # Best route estimated fee (USDT): 1.0 * 16,000 = 16,000 IDR
    # Since expected yield (41.6) < fee (16000), it should block!
    print("Testing unprofitable bridge routing (blocking check)...")
    res = await router.auto_bridge_to_phantom(
        amount_idr=10000.0,
        destination_address="5z5DLANN9CLd2SYQmMzSZEX6UHzz3FKNwDkMBgZTM8m8",
        target_network="polygon",
        target_apy=5.0
    )
    print(f"Bridge result (expected blocked): {res}, state resolved: {router.state}")
    assert res is False, "BridgeRouter should have blocked unprofitable transfer"
    assert router.state == "blocked", "BridgeRouter state must transition to 'blocked'"
    
    # 2. Test simulation mode enforcement (KIBOT_ENABLE_REAL_BRIDGE & KIBOT_ENABLE_REAL_WITHDRAWAL are false/missing)
    # Expected yield: 10,000,000 * 30% APY / 12 = 250,000 IDR
    # Best route fee: 16,000 IDR
    # Expected yield (250000) > fee (16000), profitability check passes!
    # But since KIBOT_ENABLE_REAL_BRIDGE & KIBOT_ENABLE_REAL_WITHDRAWAL are false, it should run simulation!
    print("Testing simulation mode enforcement...")
    with patch.dict(os.environ, {"KIBOT_ENABLE_REAL_BRIDGE": "false", "KIBOT_ENABLE_REAL_WITHDRAWAL": "false"}):
        res2 = await router.auto_bridge_to_phantom(
            amount_idr=10000000.0,
            destination_address="5z5DLANN9CLd2SYQmMzSZEX6UHzz3FKNwDkMBgZTM8m8",
            target_network="polygon",
            target_apy=30.0
        )
        print(f"Bridge result (expected simulation): {res2}, state resolved: {router.state}")
        assert res2 is True, "BridgeRouter should simulate success in simulation mode"
        assert router.state == "executed", "BridgeRouter state must transition to 'executed'"
        
    print("SUCCESS: BridgeRouter correctly blocked unprofitable trades and enforced simulation mode.")


async def run_all_tests():
    test_riskgate_drawdown_lock()
    await test_phantom_live_trading_gate()
    await test_search_service_resilience()
    await test_bridge_router_hardening()
    print("\n=========================================")
    print("ALL HARDENING VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("=========================================\n")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
