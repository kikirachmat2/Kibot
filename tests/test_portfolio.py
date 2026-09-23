"""
Unit tests for PortfolioTracker.
"""

import pytest
from storage.database import Database
from core.portfolio import PortfolioTracker


def test_record_buy_trade_cost_basis(tmp_path):
    db_file = str(tmp_path / "test_portfolio.db")
    db = Database(db_file)
    tracker = PortfolioTracker(db)

    # Buy 1: 0.01 BTC at Rp 1,000,000,000 (Fee = Rp 11,110)
    tracker.record_trade(
        pair="btc_idr",
        side="BUY",
        price=1_000_000_000.0,
        amount=0.01,
        fee=11_110.0,
        fee_asset="IDR",
        is_paper=True
    )

    pos = tracker.get_position("BTC")
    assert pos is not None
    assert pos.amount == 0.01
    assert pos.total_invested_idr == 10_011_110.0
    assert round(pos.cost_basis_idr, 2) == 1_001_111_000.0

    # Buy 2: 0.01 BTC at Rp 1,200,000,000 (Fee = Rp 13,332)
    tracker.record_trade(
        pair="btc_idr",
        side="BUY",
        price=1_200_000_000.0,
        amount=0.01,
        fee=13_332.0,
        fee_asset="IDR",
        is_paper=True
    )

    pos2 = tracker.get_position("BTC")
    assert pos2.amount == 0.02
    assert pos2.total_invested_idr == 10_011_110.0 + 12_013_332.0
    # Cost basis per unit = total invested / 0.02
    expected_basis = (10_011_110.0 + 12_013_332.0) / 0.02
    assert round(pos2.cost_basis_idr, 2) == round(expected_basis, 2)


def test_record_sell_trade(tmp_path):
    db_file = str(tmp_path / "test_portfolio.db")
    db = Database(db_file)
    tracker = PortfolioTracker(db)

    tracker.record_trade(
        pair="btc_idr",
        side="BUY",
        price=1_000_000_000.0,
        amount=0.02,
        fee=0.0,
        fee_asset="IDR"
    )

    # Sell half (0.01 BTC)
    tracker.record_trade(
        pair="btc_idr",
        side="SELL",
        price=1_500_000_000.0,
        amount=0.01,
        fee=0.0,
        fee_asset="IDR"
    )

    pos = tracker.get_position("BTC")
    assert pos.amount == 0.01
    assert pos.cost_basis_idr == 1_000_000_000.0
    assert pos.total_invested_idr == 10_000_000.0


def test_process_manual_asset_disposal(tmp_path):
    db_file = str(tmp_path / "test_portfolio_disp.db")
    db = Database(db_file)
    tracker = PortfolioTracker(db)

    # Buy 0.02 BTC @ 1,000,000,000
    tracker.record_trade("btc_idr", "BUY", 1_000_000_000.0, 0.02, 0.0, "IDR")

    # Supervisor sells 0.01 BTC manually in Indodax app @ estimated market price 1,400,000,000
    res = tracker.process_manual_asset_disposal(
        asset="BTC",
        amount_disposed=0.01,
        estimated_market_price=1_400_000_000.0
    )

    assert res["asset"] == "BTC"
    assert res["amount_disposed"] == 0.01
    assert res["cost_basis_idr"] == 1_000_000_000.0
    assert res["estimated_proceeds_idr"] == 14_000_000.0
    assert res["estimated_realized_pnl_idr"] == 4_000_000.0
    assert res["remaining_amount"] == 0.01

    pos = tracker.get_position("BTC")
    assert pos.amount == 0.01
    assert pos.cost_basis_idr == 1_000_000_000.0
    assert pos.total_invested_idr == 10_000_000.0


def test_portfolio_snapshot(tmp_path):
    db_file = str(tmp_path / "test_portfolio.db")
    db = Database(db_file)
    tracker = PortfolioTracker(db)

    tracker.record_trade("btc_idr", "BUY", 1_000_000_000.0, 0.001, 0.0, "IDR")
    tracker.record_trade("eth_idr", "BUY", 50_000_000.0, 0.02, 0.0, "IDR")

    prices = {"BTC": 1_000_000_000.0, "ETH": 50_000_000.0}
    snapshot = tracker.take_snapshot(cash_idr=1_000_000.0, asset_prices=prices, regime_phase="EARLY_BULL")

    # Equity: Cash 1M + BTC 1M + ETH 1M = 3M
    assert snapshot["total_equity_idr"] == 3_000_000.0
    assert snapshot["allocations"]["IDR"] == 0.3333
    assert snapshot["allocations"]["BTC"] == 0.3333
    assert snapshot["allocations"]["ETH"] == 0.3333
