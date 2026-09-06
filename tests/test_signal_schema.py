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
async def test_signal_schema_validation():
    executor = IndodaxExecutor()
    executor.active_trades = {}
    executor._save_active_trades = MagicMock()
    
    # 1. Invalid signal type (not COUNCIL_MANDATE)
    bad_type_signal = {"symbol": "BTC/IDR", "side": "BUY", "type": "AUTO_PILOT"}
    with patch.object(KiConfig, 'CANARY_LIVE_ENABLED', True), \
         patch.object(executor.indodax, 'trade', new_callable=AsyncMock) as mock_trade:
        
        await executor.process_signal(bad_type_signal)
        mock_trade.assert_not_called()

@pytest.mark.anyio
async def test_signal_schema_missing_expected_ev():
    executor = IndodaxExecutor()
    executor.active_trades = {}
    executor._save_active_trades = MagicMock()
    
    # 2. Schema check for missing expected EV fields
    no_ev_signal = {"symbol": "BTC/IDR", "side": "BUY", "type": "COUNCIL_MANDATE"}
    # Expected net check uses load_strategy() under the hood
    mock_strategy = {
        "indodax": {
            "fee_roundtrip_pct": 1.02,
            "take_profit_pct": 0.5  # tp_pct - fee = 0.5 - 1.02 = -0.52 (non-positive)
        }
    }
    with patch.object(KiConfig, 'CANARY_LIVE_ENABLED', True), \
         patch.dict(os.environ, {"KIBOT_CANARY_REQUIRE_POSITIVE_EV": "true"}), \
         patch('Core.Executors.Indodax.indodax_executor.load_strategy', return_value=mock_strategy), \
         patch.object(executor.indodax, 'trade', new_callable=AsyncMock) as mock_trade:
        
        await executor.process_signal(no_ev_signal)
        mock_trade.assert_not_called()
