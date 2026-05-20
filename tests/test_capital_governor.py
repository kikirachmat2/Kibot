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


def _isolate_runtime_state(monkeypatch, tmp_path: Path) -> Path:
    """Keep tests from mutating the operator's live state directory."""
    import Core.Treasury.capital_governor as capital_module
    import Core.Treasury.venue_ledger as ledger_module
    import Core.Treasury.phantom_treasury as phantom_module
    import Core.risk_gate as risk_module

    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(capital_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(capital_module, "GOVERNOR_FILE", tmp_path / "capital_governor.json")
    monkeypatch.setattr(capital_module, "ANCHOR_FILE", tmp_path / "daily_equity_anchor.json")
    monkeypatch.setattr(ledger_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(ledger_module, "LEDGER_FILE", tmp_path / "venue_ledger.json")
    monkeypatch.setattr(phantom_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(phantom_module, "PHANTOM_STATE_FILE", tmp_path / "phantom_treasury.json")
    monkeypatch.setattr(
        phantom_module,
        "PHANTOM_RECONCILIATION_FILE",
        tmp_path / "TREASURY_RECONCILIATION_REQUIRED",
    )
    monkeypatch.setattr(risk_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(risk_module, "RISK_STATE_FILE", tmp_path / "risk_state.json")
    monkeypatch.setitem(globals(), "GOVERNOR_FILE", tmp_path / "capital_governor.json")
    return tmp_path


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

def test_venue_ledger(monkeypatch, tmp_path):
    _isolate_runtime_state(monkeypatch, tmp_path)
    ledger = VenueLedger()
    
    # Test setting and updating venues
    ledger.update_venue("indodax_real", equity_idr=250000.0)
    ledger.update_venue("phantom", equity_idr=50000.0)
    
    v_indo = ledger.get_venue("indodax_real")
    assert v_indo["equity_idr"] == 250000.0
    
    v_phantom = ledger.get_venue("phantom")
    assert v_phantom["equity_idr"] == 50000.0

@pytest.mark.anyio
async def test_phantom_treasury(monkeypatch, tmp_path):
    _isolate_runtime_state(monkeypatch, tmp_path)
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
async def test_capital_governor_drawdown_enforcement(monkeypatch, tmp_path):
    _isolate_runtime_state(monkeypatch, tmp_path)
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
        assert gov_data["total_balance_idr"] == 180000.0
        assert gov_data["combined_pnl_idr"] == gov_data["daily_pnl_idr"]
        assert gov_data["reset_total_balance_idr"] == gov_data["start_total_equity_idr"]
        
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


@pytest.mark.anyio
async def test_capital_governor_global_hard_stop_flags_blocked(monkeypatch, tmp_path):
    _isolate_runtime_state(monkeypatch, tmp_path)
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

    with patch.object(KiConfig, "LIVE_TRADING_ENABLED", True), \
         patch.object(KiConfig, "ENABLE_POLYMARKET_LIVE", False):
        governor = CapitalGovernor(indodax, router)
        governor.start_total_equity_idr = 100000.0
        governor.current_total_equity_idr = 95000.0
        governor.max_daily_loss_idr = 1500.0
        governor.daily_pnl_idr = -2000.0
        governor.status = "RECONCILED"
        governor.allow_new_orders = True
        governor.allow_new_orders_reason = ""
        governor.save()

    data = json.loads(GOVERNOR_FILE.read_text(encoding="utf-8"))
    assert data["global_hard_stop"] is True
    assert data["status"] == "BLOCKED_WITH_REASON"
    assert data["allow_new_orders"] is False

@pytest.mark.anyio
async def test_capital_governor_flows_and_hardenings(monkeypatch, tmp_path):
    _isolate_runtime_state(monkeypatch, tmp_path)
    # Setup mock Indodax and Phantom router
    indodax = AsyncMock()
    indodax.get_info = AsyncMock(return_value={
        "success": 1,
        "return": {
            "balance": {
                "idr": 200000.0
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
    
    # 1. Test transfer parsing & PnL accounting
    # Create a temporary treasury_transfers.jsonl
    from Core.Treasury.capital_governor import STATE_DIR, GOVERNOR_FILE
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    transfers_file = STATE_DIR / "treasury_transfers.jsonl"
    
    from datetime import datetime
    import pytz
    wib = pytz.timezone('Asia/Jakarta')
    today_str = datetime.now(wib).strftime('%Y-%m-%d')
    
    # Write some transfers: one internal, one deposit (flow), one withdrawal (flow)
    records = [
        {"date": today_str, "timestamp": "", "type": "internal", "amount_idr": 30000.0, "description": "internal move"},
        {"date": today_str, "timestamp": "", "type": "deposit", "amount_idr": 10000.0, "description": "external deposit"},
        {"date": today_str, "timestamp": "", "type": "withdrawal", "amount_idr": 5000.0, "description": "external withdrawal"}
    ]
    with open(transfers_file, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
            
    with patch.object(KiConfig, "LIVE_TRADING_ENABLED", True), \
         patch.object(KiConfig, "ENABLE_POLYMARKET_LIVE", False):
         
        governor = CapitalGovernor(indodax, router)
        governor.start_total_equity_idr = 0.0
        
        gov_data = await governor.reconcile_governor()
        # total_equity = 200k + (5 * 16000) = 280,000 IDR
        assert gov_data["current_total_equity_idr"] == 280000.0
        # start_total_equity = 280,000 IDR
        # external_deposits_today = 10,000 IDR
        # external_withdrawals_today = 5,000 IDR
        # PnL should be adjusted: current - start - deposits + withdrawals
        # 280,000 - 280,000 - 10,000 + 5,000 = -5,000 IDR
        assert gov_data["daily_pnl_idr"] == -5000.0
        assert gov_data["daily_pnl_pct"] == (-5000.0 / 280000.0 * 100.0)
        assert gov_data["status"] == "BLOCKED_WITH_REASON"
        assert gov_data["allow_new_orders"] is False
        
        # Clean up transfers file
        if transfers_file.exists():
            transfers_file.unlink()

    # 2. Test RiskGate hardening for Unreconciled Status
    governor.daily_pnl_idr = 0.0
    governor.max_daily_loss_idr = 0.0
    governor.status = "UNRECONCILED"
    governor.save()
    
    risk = RiskGate()
    signal = {"symbol": "BTC_IDR", "expected_net_pct": 5.0}
    is_valid, reason = risk.validate_signal(signal, balance_idr=280000.0, active_positions_count=0)
    assert not is_valid
    assert (
        "expected 'RECONCILED'" in reason
        or "Global daily loss cap reached" in reason
        or "global_daily_loss_cap_breached" in reason
    )

    # 3. Test RiskGate hardening for Staleness
    governor.status = "RECONCILED"
    governor.save()
    
    # Artificially set file mtime back by 100 seconds
    import time
    mtime = time.time() - 100
    os.utime(GOVERNOR_FILE, (mtime, mtime))
    
    is_valid, reason = risk.validate_signal(signal, balance_idr=280000.0, active_positions_count=0)
    assert not is_valid
    assert "is stale" in reason

@pytest.mark.anyio
async def test_capital_governor_manual_reset(monkeypatch, tmp_path):
    _isolate_runtime_state(monkeypatch, tmp_path)
    # Setup mock Indodax and Phantom router
    indodax = AsyncMock()
    indodax.get_info = AsyncMock(return_value={
        "success": 1,
        "return": {
            "balance": {
                "idr": 200000.0
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
    
    from Core.Treasury.capital_governor import STATE_DIR
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    transfers_file = STATE_DIR / "treasury_transfers.jsonl"
    
    from datetime import datetime
    import pytz
    wib = pytz.timezone('Asia/Jakarta')
    today_str = datetime.now(wib).strftime('%Y-%m-%d')
    
    # Write some transfers: one deposit of 20,000 IDR
    records = [
        {"date": today_str, "timestamp": "", "type": "deposit", "amount_idr": 20000.0, "description": "external deposit"}
    ]
    with open(transfers_file, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
            
    with patch.object(KiConfig, "LIVE_TRADING_ENABLED", True), \
         patch.object(KiConfig, "ENABLE_POLYMARKET_LIVE", False):
         
        governor = CapitalGovernor(indodax, router)
        governor.start_total_equity_idr = 0.0
        
        gov_data = await governor.reconcile_governor()
        # current_total_equity = 200k + 80k = 280,000 IDR
        assert gov_data["current_total_equity_idr"] == 280000.0
        # start_total_equity = 280,000 IDR
        # daily_pnl_idr = 280,000 - 280,000 - 20,000 = -20,000 IDR
        assert gov_data["daily_pnl_idr"] == -20000.0
        
        # Now trigger manual pnl reset
        governor.manual_pnl_reset()
        
        assert governor.start_total_equity_idr == 280000.0
        assert governor.reset_deposits_offset == 20000.0
        assert governor.daily_pnl_idr == 0.0
        assert governor.daily_pnl_pct == 0.0
        
        # Run reconcile again to ensure it remains at 0 with offset adjustment
        gov_data_after = await governor.reconcile_governor()
        assert gov_data_after["daily_pnl_idr"] == 0.0
        assert gov_data_after["daily_pnl_pct"] == 0.0
        
        # Now write a NEW transfer of 10,000 IDR
        with open(transfers_file, "a") as f:
            f.write(json.dumps({"date": today_str, "timestamp": "", "type": "deposit", "amount_idr": 10000.0, "description": "new deposit"}) + "\n")
            
        # Reconcile again, daily PnL should be -10,000 IDR (because of the new deposit)
        gov_data_new = await governor.reconcile_governor()
        assert gov_data_new["daily_pnl_idr"] == -10000.0
        
        # Clean up transfers file
        if transfers_file.exists():
            transfers_file.unlink()


@pytest.mark.anyio
async def test_capital_governor_includes_open_buy_reserve(monkeypatch, tmp_path):
    _isolate_runtime_state(monkeypatch, tmp_path)
    indodax = AsyncMock()
    indodax.get_info = AsyncMock(return_value={
        "success": 1,
        "return": {
            "balance": {
                "idr": 75_000.0
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

    orders_dir = tmp_path / "orders"
    orders_dir.mkdir(parents=True, exist_ok=True)
    (orders_dir / "_index.json").write_text(json.dumps({
        "open": ["buy_123"],
        "orders": {
            "buy_123": {
                "pair": "EDEN/IDR",
                "side": "BUY",
                "state": "SUBMITTED",
            }
        }
    }), encoding="utf-8")
    (orders_dir / "buy_123.json").write_text(json.dumps({
        "order_id": "buy_123",
        "pair": "EDEN/IDR",
        "side": "BUY",
        "state": "SUBMITTED",
        "budget_idr": 25_000.0,
        "exchange_order_id": "ex_buy_123",
    }), encoding="utf-8")

    with patch.object(KiConfig, "LIVE_TRADING_ENABLED", True), \
         patch.object(KiConfig, "ENABLE_POLYMARKET_LIVE", False):
        governor = CapitalGovernor(indodax, router)
        governor.start_total_equity_idr = 0.0

        gov_data = await governor.reconcile_governor()

        # 75k cash + 25k reserved order + 80k Phantom equity = 180k total.
        assert gov_data["current_total_equity_idr"] == 180000.0
        assert gov_data["open_buy_order_reserve_idr"] == 25000.0
