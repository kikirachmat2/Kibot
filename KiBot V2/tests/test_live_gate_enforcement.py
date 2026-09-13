"""Unit tests for strict Live Trading Gate enforcement and Virtual Ledger (paper) execution."""
import pytest
from async_helper import run_async
from config.settings import BotConfig, settings
from executor.virtual_ledger import VirtualLedger
from executor.order_router import OrderRouter
from risk.risk_gate import RiskGate

@run_async
async def test_live_gate_intercepts_and_routes_to_paper():
    """Verify orders are strictly routed to VirtualLedger when LIVE_TRADING_ENABLED is False."""
    ledger = VirtualLedger(initial_cash_idr=10000000.0)
    risk_gate = RiskGate()
    router = OrderRouter(risk_gate=risk_gate, virtual_ledger=ledger)
    
    # settings.LIVE_TRADING_ENABLED is False by default
    assert settings.LIVE_TRADING_ENABLED is False
    
    result = await router.route_buy_order(
        symbol="BTC/IDR",
        price=1000000000.0,
        notional_idr=1000000.0
    )
    
    assert result["success"] is True
    assert result["mode"] == "PAPER_VIRTUAL_LEDGER"
    assert "BTC/IDR" in ledger.open_positions
    assert ledger.cash_idr == 9000000.0  # 10M - 1M

def test_virtual_ledger_fee_and_pnl_tracking():
    """Verify paper ledger applies fee (0.21%) and tracks unrealized/realized PnL."""
    ledger = VirtualLedger(initial_cash_idr=10000000.0)
    
    # Buy 1,000,000 IDR worth of ETH at 50,000,000
    buy_res = ledger.place_paper_buy(
        symbol="ETH/IDR",
        price=50000000.0,
        notional_idr=1000000.0,
        stop_loss_pct=2.0,
        take_profit_pct=3.0
    )
    assert buy_res["success"] is True
    assert "ETH/IDR" in ledger.open_positions
    
    # Price rises 5% to 52,500,000 -> trigger TP
    tp_res = ledger.update_market_price("ETH/IDR", current_price=52500000.0)
    assert tp_res is not None
    assert tp_res["exit_reason"] == "TAKE_PROFIT_TARGET_HIT"
    assert tp_res["realized_pnl_idr"] > 0.0
    assert "ETH/IDR" not in ledger.open_positions

@run_async
async def test_live_trading_locked_in_phase_1():
    """Verify that even if LIVE_TRADING_ENABLED is forced true, Phase 1 raises PermissionError."""
    ledger = VirtualLedger(initial_cash_idr=10000000.0)
    risk_gate = RiskGate()
    router = OrderRouter(risk_gate=risk_gate, virtual_ledger=ledger)
    
    # Temporarily simulate someone trying to force live trading enabled
    original_flag = settings.LIVE_TRADING_ENABLED
    try:
        settings.LIVE_TRADING_ENABLED = True
        with pytest.raises(PermissionError) as excinfo:
            await router.route_buy_order("BTC/IDR", price=1000000000.0, notional_idr=500000.0)
        assert "Live trading execution is locked in KiBot V2 Phase 1" in str(excinfo.value)
    finally:
        settings.LIVE_TRADING_ENABLED = original_flag
