import pytest
import os
import json
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from Core.Treasury.allocation_policy import AllocationPolicy
from Core.Treasury.venue_ledger import VenueLedger
from Core.Treasury.phantom_treasury import PhantomTreasury
from Core.Treasury.capital_governor import CapitalGovernor, GOVERNOR_FILE
from Core.risk_gate import RiskGate
from Core.Support.ki_config import KiConfig

def test_allocation_policy():
    policy = AllocationPolicy()
    
    # If Phantom balance is 0 or negative
    targets_zero = policy.compute_targets(0.0)
    assert targets_zero["indodax"] == 0.80
    assert targets_zero["phantom"] == 0.00
    assert targets_zero["reserve"] == 0.20
    
    # If Phantom balance is positive
    targets_pos = policy.compute_targets(150000.0)
    assert targets_pos["indodax"] == 0.60
    assert targets_pos["phantom"] == 0.25
    assert targets_pos["reserve"] == 0.15

def test_venue_ledger(tmp_path):
    ledger = VenueLedger()
    
    # Test setting and updating venues
    ledger.update_venue("indodax_real", equity_idr=250000.0)
    ledger.update_venue("phantom", equity_idr=50000.0)
    
    v_indo = ledger.get_venue("indodax_real")
    assert v_indo["equity_idr"] == 250000.0
    
    v_phantom = ledger.get_venue("phantom")
    assert v_phantom["equity_idr"] == 50000.0

@pytest.mark.anyio
async def test_phantom_treasury():
    # Mock PhantomRouter
    router = MagicMock()
    router.wallet_address = "0xPhantomWalletAddress"
    router.get_balances = AsyncMock(return_value={
        "usdc_balance": 10.0,
        "sol_balance": 0.5,
        "matic_balance": 0.0
    })
    
    # Force mock KiConfig settings for a clean state
    with patch.object(KiConfig, "ENABLE_POLYMARKET_LIVE", False):
        treasury = PhantomTreasury(router)
        # Reconcile
        await treasury.reconcile_balances()
        summary = treasury.get_summary()
        
        assert summary["usdc_balance"] == 10.0
        assert summary["sol_balance"] == 0.5
        # Total: usdc ($10) + sol (0.5 * $170 = $85) = $95 * 16,000 IDR = 1,520,000 IDR
        assert summary["total_value_idr"] == 95.0 * 16000.0

@pytest.mark.anyio
async def test_capital_governor_drawdown_enforcement():
    # Setup mock Indodax and Phantom router
    indodax = AsyncMock()
    indodax.get_info = AsyncMock(return_value={
        "success": 1,
        "return": {
            "balance": {
                "idr": 100000.0
            }
        }
    })
    
    router = MagicMock()
    router.wallet_address = "0xPhantomWalletAddress"
    router.get_balances = AsyncMock(return_value={
        "usdc_balance": 5.0,
        "sol_balance": 0.0,
        "matic_balance": 0.0
    })
    
    # Enforce LIVE_TRADING_ENABLED = True for the test so we calculate with real Indodax
    with patch.object(KiConfig, "LIVE_TRADING_ENABLED", True), \
         patch.object(KiConfig, "ENABLE_POLYMARKET_LIVE", False):
         
        governor = CapitalGovernor(indodax, router)
        
        # Reset starting to 0 so check_daily_reset initializes it
        governor.start_total_equity_idr = 0.0
        
        # Reconcile capital
        gov_data = await governor.reconcile_governor()
        # total_equity = 100k + (5 * 16000) = 180,000 IDR
        assert gov_data["current_total_equity_idr"] == 180000.0
        
        # Verify GOVERNOR_FILE exists
        assert GOVERNOR_FILE.exists()
        
        # Test RiskGate enforcement against the governor's drawdown
        # Set starting equity high, but current equity low (loss greater than 1.5%)
        governor.start_total_equity_idr = 200000.0
        governor.current_total_equity_idr = 180000.0 # Loss is 20,000 IDR (10% of start_total_equity)
        governor.max_daily_loss_idr = 200000.0 * 0.015 # 3,000 IDR
        governor.daily_pnl_idr = -200000.0 * 0.10 # -20,000 IDR
        governor.save()
        
        # Test RiskGate
        risk = RiskGate()
        signal = {"symbol": "BTC_IDR", "expected_net_pct": 5.0}
        is_valid, reason = risk.validate_signal(signal, balance_idr=180000.0, active_positions_count=0)
        
        assert not is_valid
        assert "MANIFESTO CAP: Global daily loss cap reached" in reason
