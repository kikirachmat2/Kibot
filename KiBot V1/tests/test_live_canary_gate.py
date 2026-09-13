#!/usr/bin/env python3
import os
import sys
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

# Ensure project root is in the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Core.Executors.Indodax.indodax_executor import IndodaxExecutor
from Core.Support.ki_config import KiConfig

@pytest.mark.anyio
async def test_canary_kill_switch():
    executor = IndodaxExecutor()
    executor.active_trades = {}
    executor.reservations = {}
    executor._save_active_trades = MagicMock()
    signal = {"symbol": "BTC/IDR", "side": "BUY", "type": "COUNCIL_MANDATE"}
    
    # Touch KILL_SWITCH manually
    kill_switch_path = Path(executor.state_file.parent) / "KILL_SWITCH"
    kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
    kill_switch_path.touch()
    
    try:
        with patch.object(KiConfig, 'CANARY_LIVE_ENABLED', True), \
             patch.object(KiConfig, 'LIVE_TRADING_ENABLED', True), \
             patch.object(executor.indodax, 'trade', new_callable=AsyncMock) as mock_trade:
            
            await executor.process_signal(signal)
            mock_trade.assert_not_called()
    finally:
        if kill_switch_path.exists():
            kill_switch_path.unlink()

@pytest.mark.anyio
async def test_canary_budget_limit_cannot_bypass_decision_gate():
    executor = IndodaxExecutor()
    executor.active_trades = {}
    executor.reservations = {}
    executor._save_active_trades = MagicMock()
    # Let's set up the executor so it can proceed to execution
    executor._load_canary_stats = MagicMock(return_value={"date": "2026-05-17", "trade_count": 0, "daily_loss_idr": 0.0})
    executor.risk.validate_signal = MagicMock(return_value=(True, "OK"))
    executor.indodax.get_balance = AsyncMock(return_value=1000000000.0) # rich wallet
    executor.indodax.get_orderbook = AsyncMock(return_value={
        "bids": [["9995.0", "100.0"]],
        "asks": [["10005.0", "100.0"]]
    })
    
    signal = {
        "symbol": "XRP/IDR",
        "side": "BUY",
        "type": "COUNCIL_MANDATE",
        "price": 10000.0,
        "change_5m_pct": 2.5,
        "confidence": 0.85
    }
    
    # Verify that KIBOT_CANARY_MAX_TRADE_IDR is enforced as a clamp
    with patch.object(KiConfig, 'CANARY_LIVE_ENABLED', True), \
         patch.object(KiConfig, 'LIVE_TRADING_ENABLED', True), \
         patch.object(KiConfig, 'CANARY_MAX_TRADE_IDR', 25000.0), \
         patch('Core.Executors.Indodax.indodax_executor._ORDER_TRACKER_AVAILABLE', False), \
         patch('Core.Executors.Indodax.indodax_executor.load_strategy', return_value={"indodax": {"fee_roundtrip_pct": 1.02, "take_profit_pct": 1.5, "max_exposure_idr": 0, "max_slots": 10, "max_spread_pct": 1.5, "allowed_pairs": ["*"]}}), \
         patch.object(executor.indodax, 'trade', new_callable=AsyncMock) as mock_trade:
         
        mock_trade.return_value = {"success": 1, "return": {"filled_rp": 25000.0, "filled_coin": 2.5, "price": 10000.0}}
        await executor.process_signal(signal)
        
        # Legacy canary sizing must not bypass the live-only deterministic gate.
        mock_trade.assert_not_called()

@pytest.mark.anyio
async def test_canary_council_mandate_requirement():
    executor = IndodaxExecutor()
    executor.active_trades = {}
    executor.reservations = {}
    executor._save_active_trades = MagicMock()
    # A non-COUNCIL_MANDATE signal should be blocked
    signal = {"symbol": "BTC/IDR", "side": "BUY", "type": "STANDARD_SIGNAL"}
    
    with patch.object(KiConfig, 'CANARY_LIVE_ENABLED', True), \
         patch.object(KiConfig, 'CANARY_REQUIRE_COUNCIL_APPROVAL', True), \
         patch.object(executor.indodax, 'trade', new_callable=AsyncMock) as mock_trade:
         
        await executor.process_signal(signal)
        mock_trade.assert_not_called()

@pytest.mark.anyio
async def test_canary_ev_rejection():
    executor = IndodaxExecutor()
    executor.active_trades = {}
    executor.reservations = {}
    executor._save_active_trades = MagicMock()
    signal = {"symbol": "BTC/IDR", "side": "BUY", "type": "COUNCIL_MANDATE"}
    
    # We mock expected net percent to be negative or zero (e.g. tp_pct = 1.0, fee_roundtrip_pct = 1.02 -> net = -0.02)
    mock_strategy = {
        "indodax": {
            "fee_roundtrip_pct": 1.02,
            "take_profit_pct": 0.5  # Expected net = 0.5 - 1.02 = -0.52%
        }
    }
    
    with patch.object(KiConfig, 'CANARY_LIVE_ENABLED', True), \
         patch.object(KiConfig, 'CANARY_REQUIRE_POSITIVE_EV', True), \
         patch('Core.Executors.Indodax.indodax_executor.load_strategy', return_value=mock_strategy), \
         patch.object(executor.indodax, 'trade', new_callable=AsyncMock) as mock_trade:
         
        await executor.process_signal(signal)
        mock_trade.assert_not_called()

@pytest.mark.anyio
async def test_canary_position_limit():
    executor = IndodaxExecutor()
    executor.active_trades = {"BTC/IDR": {"entry_price": 100000.0}}
    executor.reservations = {}
    executor._save_active_trades = MagicMock()
    signal = {"symbol": "BTC/IDR", "side": "BUY", "type": "COUNCIL_MANDATE"}
    
    with patch.object(KiConfig, 'CANARY_LIVE_ENABLED', True), \
         patch.object(KiConfig, 'CANARY_MAX_OPEN_POSITIONS', 1), \
         patch.object(executor.indodax, 'trade', new_callable=AsyncMock) as mock_trade:
         
        await executor.process_signal(signal)
        mock_trade.assert_not_called()
