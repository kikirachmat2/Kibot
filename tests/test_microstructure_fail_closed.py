#!/usr/bin/env python3
import os
import sys
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

# Ensure project root is in the path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from Core.Executors.Indodax.indodax_executor import IndodaxExecutor
from Core.Support.ki_config import KiConfig

@pytest.mark.anyio
async def test_microstructure_fail_closed_on_exception():
    executor = IndodaxExecutor()
    signal = {"symbol": "BTC/IDR", "side": "BUY", "type": "COUNCIL_MANDATE", "budget_idr": 25000.0}
    
    # 1. Mock state and pre-trade simulation to let flow reach the microstructure check
    executor._load_canary_stats = MagicMock(return_value={"date": "2026-05-17", "trade_count": 0, "daily_loss_idr": 0.0})
    executor.risk.validate_signal = MagicMock(return_value=(True, "OK"))
    executor.indodax.get_balance = AsyncMock(return_value=1000000.0)
    executor.indodax.get_orderbook = AsyncMock(return_value={"bids": [["900000000", "0.1"]], "asks": [["910000000", "0.1"]]})
    
    # 2. Mock Microstructure Analyzer to raise an Exception
    with patch.object(KiConfig, 'CANARY_LIVE_ENABLED', True), \
         patch.object(KiConfig, 'LIVE_TRADING_ENABLED', True), \
         patch('Core.Executors.Indodax.indodax_executor.load_strategy', return_value={"indodax": {"fee_roundtrip_pct": 1.02, "take_profit_pct": 1.5, "max_exposure_idr": 0, "max_slots": 10}}), \
         patch('Core.Intelligence.indodax_microstructure.IndodaxMicrostructureAnalyzer') as mock_analyzer_cls, \
         patch.object(executor.indodax, 'trade', new_callable=AsyncMock) as mock_trade:
         
        # Mock instance of the analyzer to throw exception on analyze_liquidity
        mock_analyzer_instance = MagicMock()
        mock_analyzer_instance.analyze_liquidity.side_effect = Exception("Orderbook fetch timeout or disconnect simulation")
        mock_analyzer_cls.return_value = mock_analyzer_instance
        
        await executor.process_signal(signal)
        
        # Verify that trade was NEVER called because we failed-closed
        mock_trade.assert_not_called()

@pytest.mark.anyio
async def test_microstructure_rejection_on_fail_liquidity():
    executor = IndodaxExecutor()
    signal = {"symbol": "BTC/IDR", "side": "BUY", "type": "COUNCIL_MANDATE", "budget_idr": 25000.0}
    
    executor._load_canary_stats = MagicMock(return_value={"date": "2026-05-17", "trade_count": 0, "daily_loss_idr": 0.0})
    executor.risk.validate_signal = MagicMock(return_value=(True, "OK"))
    executor.indodax.get_balance = AsyncMock(return_value=1000000.0)
    executor.indodax.get_orderbook = AsyncMock(return_value={"bids": [["900000000", "0.1"]], "asks": [["910000000", "0.1"]]})
    
    # Mock analyzer return value showing pass_liquidity is False
    mock_analysis_fail = {
        "spread_pct": 0.5,
        "slippage_pct": 0.1,
        "pass_liquidity": False,
        "reason": "Spread is too wide"
    }
    
    with patch.object(KiConfig, 'CANARY_LIVE_ENABLED', True), \
         patch.object(KiConfig, 'LIVE_TRADING_ENABLED', True), \
         patch('Core.Executors.Indodax.indodax_executor.load_strategy', return_value={"indodax": {"fee_roundtrip_pct": 1.02, "take_profit_pct": 1.5, "max_exposure_idr": 0, "max_slots": 10}}), \
         patch('Core.Intelligence.indodax_microstructure.IndodaxMicrostructureAnalyzer') as mock_analyzer_cls, \
         patch.object(executor.indodax, 'trade', new_callable=AsyncMock) as mock_trade:
         
        mock_analyzer_instance = MagicMock()
        mock_analyzer_instance.analyze_liquidity.return_value = mock_analysis_fail
        mock_analyzer_instance.calculate_net_yield.return_value = 0.38
        mock_analyzer_cls.return_value = mock_analyzer_instance
        
        await executor.process_signal(signal)
        
        mock_trade.assert_not_called()
