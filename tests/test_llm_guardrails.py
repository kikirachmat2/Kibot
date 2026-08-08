#!/usr/bin/env python3
import os
import sys
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

# Ensure project root is in the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Core.Intelligence.kibot_ai_coordinator import query_ai, _provider_timeout, AI_SAFE_FALLBACK
from Core.Executors.Indodax.indodax_executor import IndodaxExecutor
from Core.Support.ki_config import KiConfig

@pytest.mark.anyio
async def test_llm_disabled_fallback():
    """Asserts that when KIBOT_LLM_ENABLED is False, query_ai returns AI_SAFE_FALLBACK immediately."""
    with patch.object(KiConfig, "LLM_ENABLED", False):
        res = await query_ai("MARKET_SCOUT", {"ticker": "BTC/IDR"})
        assert res == AI_SAFE_FALLBACK
        assert res["verdict"] == "REJECTED"
        assert res["is_fallback"] is True

def test_llm_provider_timeouts():
    """Asserts that _provider_timeout correctly distinguishes between standard and heavy models using KiConfig values."""
    with patch.object(KiConfig, "LLM_TIMEOUT_S", 4.0), \
         patch.object(KiConfig, "LLM_HEAVY_MODEL_TIMEOUT_S", 8.0):
        
        # Test a standard model (e.g. regime_analyst or fast_hunter)
        timeout_std = _provider_timeout("ollama", "fast_hunter")
        assert timeout_std == 4.0

        # Test a heavy model containing "7b" or "deep" (e.g. STRATEGY_DEAN or SOVEREIGN_DAILY_REVIEW)
        timeout_heavy = _provider_timeout("ollama", "STRATEGY_DEAN")
        assert timeout_heavy == 8.0

@pytest.mark.anyio
async def test_executor_llm_block():
    """Asserts that when KIBOT_LLM_BLOCK_EXECUTOR is True, process_signal aborts immediately."""
    executor = IndodaxExecutor()
    executor.active_trades = {}
    executor.reservations = {}
    executor._save_active_trades = MagicMock()
    
    signal = {"symbol": "BTC/IDR", "side": "BUY", "type": "COUNCIL_MANDATE"}

    with patch.object(KiConfig, "LLM_BLOCK_EXECUTOR", True), \
         patch.object(executor.indodax, "trade", new_callable=AsyncMock) as mock_trade:
        
        await executor.process_signal(signal)
        mock_trade.assert_not_called()

@pytest.mark.anyio
async def test_executor_llm_direct_blocked():
    """Asserts that when LLM_ALLOWED_TO_PLACE_ORDER is False, any direct LLM signal is bypassed."""
    executor = IndodaxExecutor()
    executor.active_trades = {}
    executor.reservations = {}
    executor._save_active_trades = MagicMock()
    
    # Direct LLM signal
    signal = {"symbol": "BTC/IDR", "side": "BUY", "type": "LLM_DIRECT", "origin": "LLM"}

    with patch.object(KiConfig, "LLM_ALLOWED_TO_PLACE_ORDER", False), \
         patch.object(executor.indodax, "trade", new_callable=AsyncMock) as mock_trade:
        
        await executor.process_signal(signal)
        mock_trade.assert_not_called()
