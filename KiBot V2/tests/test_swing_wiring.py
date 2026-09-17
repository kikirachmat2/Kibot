import asyncio
import time
import pytest
from unittest.mock import MagicMock, AsyncMock

from main import KiBotV2Pipeline
from council.swing_evaluator import SwingEvaluator
from council.evaluator import CouncilDecision
from executor.virtual_ledger import VirtualLedger
from executor.order_router import OrderRouter
from risk import RiskGate, CapitalGovernor
from async_helper import run_async

def test_pipeline_initializes_with_swing_evaluator():
    """Verify KiBotV2Pipeline uses SwingEvaluator instead of FastCouncilEvaluator."""
    pipeline = KiBotV2Pipeline()
    assert isinstance(pipeline.swing_evaluator, SwingEvaluator)
    assert pipeline.council_pool.evaluator is pipeline.swing_evaluator

def test_virtual_ledger_stores_swing_hold_time_and_strategy():
    """Verify VirtualLedger records strategy-specific max_hold_time_s and strategy name."""
    ledger = VirtualLedger(initial_cash_idr=10_000_000.0)

    # 1. Trend-Following position (21 days = 1,814,400s)
    tf_res = ledger.place_paper_buy(
        symbol="BTC/IDR",
        price=1_000_000_000.0,
        notional_idr=3_000_000.0,
        max_hold_time_s=21 * 86400.0,
        strategy="TREND_FOLLOWING",
    )
    assert tf_res["success"] is True
    pos_btc = ledger.open_positions["BTC/IDR"]
    assert pos_btc.max_hold_time_s == 21 * 86400.0
    assert pos_btc.strategy == "TREND_FOLLOWING"

    # 2. Mean-Reversion position (10 days = 864,000s)
    mr_res = ledger.place_paper_buy(
        symbol="ETH/IDR",
        price=50_000_000.0,
        notional_idr=3_000_000.0,
        max_hold_time_s=10 * 86400.0,
        strategy="MEAN_REVERSION",
    )
    assert mr_res["success"] is True
    pos_eth = ledger.open_positions["ETH/IDR"]
    assert pos_eth.max_hold_time_s == 10 * 86400.0
    assert pos_eth.strategy == "MEAN_REVERSION"

def test_virtual_ledger_swing_hold_time_expiry_differentiation():
    """Verify MR position expires after 10 days while TF position remains open until 21 days."""
    ledger = VirtualLedger(initial_cash_idr=10_000_000.0)

    # Open TF (BTC) and MR (ETH)
    ledger.place_paper_buy(
        symbol="BTC/IDR",
        price=1_000_000_000.0,
        notional_idr=3_000_000.0,
        max_hold_time_s=21 * 86400.0,
        strategy="TREND_FOLLOWING",
    )
    ledger.place_paper_buy(
        symbol="ETH/IDR",
        price=50_000_000.0,
        notional_idr=3_000_000.0,
        max_hold_time_s=10 * 86400.0,
        strategy="MEAN_REVERSION",
    )

    # Age both positions by 11 days (950,400s)
    now = time.time()
    eleven_days_s = 11 * 86400.0
    ledger.open_positions["BTC/IDR"].entry_time = now - eleven_days_s
    ledger.open_positions["ETH/IDR"].entry_time = now - eleven_days_s

    # Update market prices with no price movement
    btc_close = ledger.update_market_price("BTC/IDR", current_price=1_000_000_000.0)
    eth_close = ledger.update_market_price("ETH/IDR", current_price=50_000_000.0)

    # BTC should STILL BE OPEN (11d < 21d)
    assert btc_close is None
    assert "BTC/IDR" in ledger.open_positions

    # ETH should BE CLOSED via MAX_HOLD_TIME_EXPIRED (11d >= 10d)
    assert eth_close is not None
    assert eth_close["exit_reason"] == "MAX_HOLD_TIME_EXPIRED"
    assert eth_close["strategy"] == "MEAN_REVERSION"
    assert "ETH/IDR" not in ledger.open_positions

    # Age BTC to 22 days (1,900,800s)
    ledger.open_positions["BTC/IDR"].entry_time = now - (22 * 86400.0)
    btc_close_22d = ledger.update_market_price("BTC/IDR", current_price=1_000_000_000.0)

    # Now BTC should close via MAX_HOLD_TIME_EXPIRED
    assert btc_close_22d is not None
    assert btc_close_22d["exit_reason"] == "MAX_HOLD_TIME_EXPIRED"
    assert btc_close_22d["strategy"] == "TREND_FOLLOWING"
    assert "BTC/IDR" not in ledger.open_positions

@run_async
async def test_order_router_forwards_swing_decision_metadata():
    """Verify OrderRouter forwards max_hold_time_s and strategy to VirtualLedger."""
    virtual_ledger = VirtualLedger(initial_cash_idr=10_000_000.0)
    router = OrderRouter(
        risk_gate=RiskGate(),
        virtual_ledger=virtual_ledger,
        capital_governor=CapitalGovernor(),
    )

    decision = CouncilDecision(
        verdict="APPROVED",
        symbol="BTC/IDR",
        action="BUY",
        confidence=0.88,
        score=86.5,
        reason="Swing TF Test",
        suggested_size_idr=3_000_000.0,
        ev_pct=0.38,
        kelly_fraction=0.0244,
        rr_ratio=1.34,
        deliberation_duration_ms=0.1,
        enrichment_status="1D_SWING_TF",
        target_tp_pct=8.5,
        target_sl_pct=5.1,
        strategy="TREND_FOLLOWING",
        max_hold_time_s=21 * 86400,
    )

    res = await router.route_buy_order(
        symbol=decision.symbol,
        price=1_000_000_000.0,
        notional_idr=decision.suggested_size_idr,
        take_profit_pct=decision.target_tp_pct,
        stop_loss_pct=decision.target_sl_pct,
        max_hold_time_s=decision.max_hold_time_s,
        strategy=decision.strategy,
    )

    assert res["success"] is True
    pos = virtual_ledger.open_positions["BTC/IDR"]
    assert pos.max_hold_time_s == 21 * 86400
    assert pos.strategy == "TREND_FOLLOWING"
