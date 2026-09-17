import pytest
import time
from unittest.mock import patch

from config import settings
from executor.virtual_ledger import VirtualLedger, VirtualPosition

def test_hybrid_exit_tp1_capital_recycling_and_breakeven_ratchet():
    """
    Test Tier 1 Partial Take Profit:
    - Entry at 1,000,000,000 IDR (BTC), Notional 2,000,000 IDR.
    - TP total = +8.0%, TP1 (50%) = +4.0% (target 1,041,040,000).
    - When price hits TP1:
      * 50% lot is closed.
      * Cash ledger receives 50% capital + profit (recycled).
      * Stop Loss of remaining 50% is ratcheted to BEP + Roundtrip Fee buffer.
      * tp1_executed is True.
    """
    initial_cash = 10_000_000.0
    ledger = VirtualLedger(initial_cash_idr=initial_cash, name="TEST_TF")

    buy_res = ledger.place_paper_buy(
        symbol="BTC/IDR",
        price=1_000_000_000.0,
        notional_idr=2_000_000.0,
        stop_loss_pct=3.5,
        take_profit_pct=8.0,
        partial_tp_pct=50.0,
        strategy="TREND_FOLLOWING",
    )
    assert buy_res["success"] is True
    pos = ledger.open_positions["BTC/IDR"]
    initial_coins = pos.amount_coins
    initial_sl = pos.stop_loss_price
    initial_cost = pos.cost_idr
    tp1_target = pos.partial_tp_price

    # Verify TP1 target is correctly calculated
    assert tp1_target > pos.entry_price
    assert tp1_target < pos.take_profit_price
    assert not pos.tp1_executed

    # Price moves slightly above entry but below TP1 -> no trigger
    res_sub = ledger.update_market_price("BTC/IDR", current_price=pos.entry_price * 1.02)
    assert res_sub is None
    assert not pos.tp1_executed
    assert pos.amount_coins == initial_coins

    # Price hits TP1 target
    cash_before_tp1 = ledger.cash_idr
    res_tp1 = ledger.update_market_price("BTC/IDR", current_price=tp1_target + 500.0)
    assert res_tp1 is None  # Position is not closed, runner is still active!
    
    # Verify Tier 1 execution
    assert pos.tp1_executed is True
    assert pytest.approx(pos.amount_coins, rel=1e-4) == (initial_coins * 0.5)
    assert pytest.approx(pos.cost_idr, rel=1e-4) == (initial_cost * 0.5)
    assert pos.partial_pnl_idr > 0
    assert ledger.cash_idr > cash_before_tp1  # Recycled capital added back to cash
    
    # Verify Break-Even Ratchet: SL must be strictly above entry price (Entry + Fee Buffer)
    assert pos.stop_loss_price > pos.entry_price
    assert pos.stop_loss_price > initial_sl

def test_hybrid_exit_reversal_to_ratcheted_breakeven():
    """
    Test scenario where price hits TP1, then market pulls back and breaches ratcheted BEP:
    - Sisa 50% closed at BEP.
    - Reason is 'BREAKEVEN_STOP_BREACHED'.
    - Total trade realized PnL remains positive (net profit locked).
    """
    initial_cash = 10_000_000.0
    ledger = VirtualLedger(initial_cash_idr=initial_cash, name="TEST_TF")

    ledger.place_paper_buy(
        symbol="BTC/IDR",
        price=1_000_000_000.0,
        notional_idr=2_000_000.0,
        stop_loss_pct=3.0,
        take_profit_pct=8.0,
        partial_tp_pct=50.0,
    )
    pos = ledger.open_positions["BTC/IDR"]
    tp1_price = pos.partial_tp_price

    # 1. Trigger TP1
    ledger.update_market_price("BTC/IDR", current_price=tp1_price + 1000.0)
    assert pos.tp1_executed is True
    ratcheted_sl = pos.stop_loss_price

    # 2. Market reverses and breaches ratcheted BEP
    close_record = ledger.update_market_price("BTC/IDR", current_price=ratcheted_sl - 500.0)
    assert close_record is not None
    assert close_record["exit_reason"] == "BREAKEVEN_STOP_BREACHED"
    assert close_record["tp1_executed"] is True
    assert close_record["partial_pnl_idr"] > 0
    # Net trade PnL MUST be strictly positive!
    assert close_record["realized_pnl_idr"] > 0
    assert "BTC/IDR" not in ledger.open_positions

def test_hybrid_exit_fat_tail_runner_full_target():
    """
    Test scenario where price hits TP1, continues rally, and hits full TP2 runner target:
    - Sisa 50% closed at full TP2.
    - Reason is 'TAKE_PROFIT_TARGET_HIT'.
    - Total trade realizes maximum fat-tail profit.
    """
    initial_cash = 10_000_000.0
    ledger = VirtualLedger(initial_cash_idr=initial_cash, name="TEST_TF")

    ledger.place_paper_buy(
        symbol="ETH/IDR",
        price=50_000_000.0,
        notional_idr=2_000_000.0,
        stop_loss_pct=3.5,
        take_profit_pct=8.0,
        partial_tp_pct=50.0,
    )
    pos = ledger.open_positions["ETH/IDR"]

    # 1. Trigger TP1
    ledger.update_market_price("ETH/IDR", current_price=pos.partial_tp_price + 100.0)
    assert pos.tp1_executed is True
    partial_pnl = pos.partial_pnl_idr

    # 2. Price keeps surging to full TP2 target
    close_record = ledger.update_market_price("ETH/IDR", current_price=pos.take_profit_price + 10_000.0)
    assert close_record is not None
    assert close_record["exit_reason"] == "TAKE_PROFIT_TARGET_HIT"
    assert close_record["tp1_executed"] is True
    assert close_record["partial_pnl_idr"] == round(partial_pnl, 2)
    assert close_record["remaining_pnl_idr"] > partial_pnl
    assert close_record["realized_pnl_idr"] > (2 * partial_pnl * 0.9)

def test_hybrid_exit_minimum_lot_protection():
    """
    Test What-If Indodax Minimum Lot restriction:
    - If remaining or closed notional is < Rp 10,000, partial exit must be skipped
      to prevent unmarketable dust on the exchange.
    """
    ledger = VirtualLedger(initial_cash_idr=100_000.0, name="TEST_TF")
    # Buy only Rp 15,000 worth (50% is Rp 7,500 < Rp 10,000 min lot)
    ledger.place_paper_buy(
        symbol="SOL/IDR",
        price=2_000_000.0,
        notional_idr=15_000.0,
        stop_loss_pct=3.0,
        take_profit_pct=8.0,
        partial_tp_pct=50.0,
    )
    pos = ledger.open_positions["SOL/IDR"]
    initial_coins = pos.amount_coins

    # Price hits partial TP price
    res = ledger.update_market_price("SOL/IDR", current_price=pos.partial_tp_price + 100.0)
    assert res is None
    # Partial TP skipped because remaining lot < Rp 10,000
    assert not pos.tp1_executed
    assert pos.amount_coins == initial_coins

def test_hybrid_exit_state_serialization_roundtrip():
    """
    Test durable state serialization and deserialization of VirtualPosition with partial TP fields.
    """
    pos = VirtualPosition(
        position_id="paper_BTC_123",
        symbol="BTC/IDR",
        side="BUY",
        entry_price=1_000_000_000.0,
        current_price=1_045_000_000.0,
        amount_coins=0.001,
        cost_idr=1_000_000.0,
        entry_time=time.time(),
        stop_loss_price=1_005_200_000.0,
        take_profit_price=1_080_000_000.0,
        max_price_seen=1_045_000_000.0,
        max_hold_time_s=21 * 86400.0,
        strategy="TREND_FOLLOWING",
        partial_tp_pct=50.0,
        partial_tp_price=1_040_000_000.0,
        tp1_executed=True,
        partial_pnl_idr=38_500.0,
        initial_cost_idr=2_000_000.0,
    )

    data = pos.to_dict()
    assert data["tp1_executed"] is True
    assert data["partial_pnl_idr"] == 38_500.0
    assert data["partial_tp_price"] == 1_040_000_000.0
    assert data["initial_cost_idr"] == 2_000_000.0

    restored = VirtualPosition.from_dict(data)
    assert restored.tp1_executed is True
    assert restored.partial_pnl_idr == 38_500.0
    assert restored.partial_tp_price == 1_040_000_000.0
    assert restored.stop_loss_price == 1_005_200_000.0
    assert restored.initial_cost_idr == 2_000_000.0
