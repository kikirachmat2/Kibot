"""
Unit Tests for KiBot V3:
1. Smart Limit 'Wick Catcher' DCA Execution with Maker Fee optimization
2. 4-Hour TTL Watchdog Fallback to Market Order
3. Multi-Condition Partial Profit Taking (4-Lock Guardrail)
4. Interactive Telegram Commands (/smartdca, /profittake, /limits)
"""

import time
import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from storage.database import Database
from core.portfolio import PortfolioTracker
from main import KiBotV3Orchestrator
from ingestion.indodax_client import IndodaxClient


@pytest.fixture
def temp_db(tmp_path):
    db_file = str(tmp_path / "kibot_smart_test.db")
    return Database(db_file)


@pytest.fixture
def orchestrator(temp_db):
    mock_indodax = AsyncMock(spec=IndodaxClient)
    orc = KiBotV3Orchestrator(
        db_path=temp_db.db_path,
        paper_mode=True,
        indodax_client=mock_indodax
    )
    # Set known prices
    orc._price_cache = {
        "BTC": 1_000_000_000.0,
        "ETH": 50_000_000.0,
        "USDT": 17_500.0
    }
    orc._price_cache_ts = 9999999999.0
    return orc


def test_calculate_floating_pnl(temp_db):
    tracker = PortfolioTracker(temp_db)
    # Record buy 0.1 BTC @ 1,000,000,000 IDR (Cost = 100,000,000)
    tracker.record_trade("BTC_IDR", "BUY", price=1_000_000_000.0, amount=0.1, fee=100_000.0, fee_asset="IDR")
    
    # Market price increases to 1,300,000,000 IDR (+30%)
    prices = {"BTC": 1_300_000_000.0}
    pnl_data = tracker.calculate_floating_pnl(prices)
    
    btc_pnl = pnl_data["positions"]["BTC"]
    assert btc_pnl["amount"] == 0.1
    assert btc_pnl["market_value_idr"] == 130_000_000.0
    assert btc_pnl["unrealized_pnl_pct"] > 29.0
    assert pnl_data["total_unrealized_pnl_pct"] > 29.0


def test_smart_limit_dca_execution(orchestrator):
    async def _run():
        # Top up 1,000,000 IDR
        orchestrator.portfolio.deposit_cash(1_000_000.0)
        
        res = await orchestrator.execute_smart_limit_dca(1_000_000.0, discount_pct=0.005) # 0.5% discount
        assert res["success"] is True
        assert res["is_smart_limit"] is True
        
        # 70% BTC = 700k, 30% ETH = 300k
        assert res["deploy_breakdown"]["BTC"] == 700_000.0
        assert res["deploy_breakdown"]["ETH"] == 300_000.0
        
        # Check open orders in DB
        open_orders = orchestrator.portfolio.get_open_orders(status="OPEN")
        assert len(open_orders) == 2
        pairs = {o["pair"] for o in open_orders}
        assert pairs == {"BTC_IDR", "ETH_IDR"}
        
        # Verify limit prices: BTC 1B * 0.995 = 995,000,000
        btc_order = next(o for o in open_orders if o["pair"] == "BTC_IDR")
        assert btc_order["price"] == 995_000_000.0
        assert btc_order["side"] == "BUY"

    asyncio.run(_run())


def test_ttl_watchdog_expires_limit_order(orchestrator):
    async def _run():
        # Save an expired limit order (expired 10 minutes ago)
        past_exp = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        order_id = orchestrator.portfolio.save_open_order(
            pair="BTC_IDR",
            side="BUY",
            order_type="LIMIT",
            price=950_000_000.0,
            amount=0.001,
            amount_idr=950_000.0,
            expires_at=past_exp,
            is_paper=True
        )
        
        # Run watchdog
        expired = await orchestrator.check_and_expire_limit_orders()
        assert len(expired) == 1
        assert expired[0]["asset"] == "BTC"
        assert expired[0]["status"] == "EXPIRED_MARKET_FILLED"
        
        # Verify order is marked as EXPIRED_MARKET_FILLED in DB
        remaining_open = orchestrator.portfolio.get_open_orders(status="OPEN")
        assert len(remaining_open) == 0

    asyncio.run(_run())


def test_partial_profit_taking_quadruple_lock(orchestrator):
    async def _run():
        # Buy 0.1 BTC @ 1,000,000,000 (Cost = 100,000,000)
        orchestrator.portfolio.record_trade("BTC_IDR", "BUY", price=1_000_000_000.0, amount=0.1, fee=100_000.0, fee_asset="IDR")
        
        # CASE 1: PnL < 25% (Price 1,100,000,000 = +10%), F&G = 80 (Extreme Greed) -> Rejected (PnL not reached)
        orchestrator._price_cache["BTC"] = 1_100_000_000.0
        res1 = await orchestrator.evaluate_and_execute_partial_profit_take(fear_greed_score=80)
        assert res1["total_executed"] == 0
        assert "target" in res1["evaluated"][0]["reason"]
        
        # CASE 2: PnL >= +25% (Price 1,350,000,000 = +35%), but F&G = 65 (Not Extreme Greed) -> Rejected
        orchestrator._price_cache["BTC"] = 1_350_000_000.0
        res2 = await orchestrator.evaluate_and_execute_partial_profit_take(fear_greed_score=65)
        assert res2["total_executed"] == 0
        assert "Extreme Greed" in res2["evaluated"][0]["reason"]
        
        # CASE 3: All locks satisfied: PnL +35%, F&G 82, sell value >> 50k, no cooldown -> EXECUTED!
        res3 = await orchestrator.evaluate_and_execute_partial_profit_take(fear_greed_score=82)
        assert res3["total_executed"] == 1
        assert res3["executed_sells"][0]["asset"] == "BTC"
        
        # Sells 15% of 0.1 BTC = 0.015 BTC
        assert res3["executed_sells"][0]["amount_sold"] == 0.015
        
        # Verify remaining position
        pos = orchestrator.portfolio.get_position("BTC")
        assert round(pos.amount, 6) == 0.085
        
        # Verify proceeds were deposited to cash IDR
        cash_pos = orchestrator.portfolio.get_position("IDR")
        assert cash_pos.amount > 0
        
        # CASE 4: Immediate re-evaluation -> Rejected due to 14-day Cooldown
        res4 = await orchestrator.evaluate_and_execute_partial_profit_take(fear_greed_score=85)
        assert res4["total_executed"] == 0
        assert "cooldown" in res4["evaluated"][0]["reason"]

    asyncio.run(_run())


def test_telegram_commands_smartdca_and_profittake(orchestrator):
    async def _run():
        # Test /smartdca
        reply1 = await orchestrator.handle_command_async("/smartdca 1000000 0.4")
        assert "SMART LIMIT DCA AKTIF" in reply1
        assert "Diskon Bid: 0.4%" in reply1
        
        # Test /limits
        reply2 = await orchestrator.handle_command_async("/limits")
        assert "DAFTAR OPEN LIMIT ORDERS" in reply2
        
        # Test /profittake
        reply3 = await orchestrator.handle_command_async("/profittake 70")
        assert "EVALUASI PARTIAL PROFIT TAKING" in reply3
        assert "Fear & Greed Index: 70" in reply3

    asyncio.run(_run())
