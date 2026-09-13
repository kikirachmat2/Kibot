"""Unit and lifecycle verification of position exit reasons in VirtualLedger:
1. TAKE_PROFIT_TARGET_HIT
2. STOP_LOSS_BREACHED
3. MAX_HOLD_TIME_EXPIRED
"""
import time
import pytest
from executor.virtual_ledger import VirtualLedger

def test_lifecycle_take_profit_hit():
    """Verify position closes with TAKE_PROFIT_TARGET_HIT when price breaches TP target."""
    ledger = VirtualLedger(initial_cash_idr=10_000_000.0)
    
    # Buy ETH at 50,000,000 IDR with TP=3.5% (TP target = 51,750,000), SL=1.5%
    buy_res = ledger.place_paper_buy(
        symbol="ETH/IDR",
        price=50_000_000.0,
        notional_idr=1_000_000.0,
        take_profit_pct=3.5,
        stop_loss_pct=1.5
    )
    assert buy_res["success"] is True
    assert "ETH/IDR" in ledger.open_positions
    pos = ledger.open_positions["ETH/IDR"]
    
    # Market moves up past TP target
    tp_target = pos.take_profit_price
    close_record = ledger.update_market_price("ETH/IDR", current_price=tp_target + 10_000.0)
    
    assert close_record is not None
    assert close_record["exit_reason"] == "TAKE_PROFIT_TARGET_HIT"
    assert close_record["realized_pnl_idr"] > 0.0
    assert "ETH/IDR" not in ledger.open_positions

def test_lifecycle_stop_loss_breached():
    """Verify position closes with STOP_LOSS_BREACHED when price drops below SL."""
    ledger = VirtualLedger(initial_cash_idr=10_000_000.0)
    
    # Buy SOL at 2,000,000 IDR with SL=1.5% (SL threshold = 1,970,000)
    buy_res = ledger.place_paper_buy(
        symbol="SOL/IDR",
        price=2_000_000.0,
        notional_idr=1_000_000.0,
        take_profit_pct=3.5,
        stop_loss_pct=1.5
    )
    assert buy_res["success"] is True
    pos = ledger.open_positions["SOL/IDR"]
    
    # Market plunges below SL
    sl_threshold = pos.stop_loss_price
    close_record = ledger.update_market_price("SOL/IDR", current_price=sl_threshold - 5_000.0)
    
    assert close_record is not None
    assert close_record["exit_reason"] == "STOP_LOSS_BREACHED"
    assert close_record["realized_pnl_idr"] < 0.0
    assert "SOL/IDR" not in ledger.open_positions

def test_lifecycle_max_hold_time_expired():
    """Verify position closes with MAX_HOLD_TIME_EXPIRED when hold duration expires."""
    ledger = VirtualLedger(initial_cash_idr=10_000_000.0)
    
    # Buy BTC at 1,000,000,000 IDR
    buy_res = ledger.place_paper_buy(
        symbol="BTC/IDR",
        price=1_000_000_000.0,
        notional_idr=1_000_000.0
    )
    assert buy_res["success"] is True
    pos = ledger.open_positions["BTC/IDR"]
    
    # Manually age the position entry time by 1000 seconds (max_hold_time_s = 900s)
    pos.entry_time = time.time() - 1000.0
    
    # Normal price update within TP/SL bands
    close_record = ledger.update_market_price("BTC/IDR", current_price=pos.entry_price, max_hold_time_s=900.0)
    
    assert close_record is not None
    assert close_record["exit_reason"] == "MAX_HOLD_TIME_EXPIRED"
    assert "BTC/IDR" not in ledger.open_positions
    assert close_record["hold_duration_s"] >= 900.0
