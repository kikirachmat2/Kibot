import asyncio
import time
import pytest
from unittest.mock import MagicMock, patch

from executor.virtual_ledger import VirtualLedger
from executor.order_router import OrderRouter
from risk import RiskGate, CapitalGovernor
from storage.live_readiness import LiveReadinessEvaluator, live_readiness_evaluator, shadow_mr_readiness_evaluator
from storage.durable_state import DurableStateStore
from config import settings


@pytest.mark.anyio
async def test_order_router_separates_tf_and_mr_ledgers():
    """Verify OrderRouter routes TF orders to primary virtual_ledger and MR orders to shadow_ledger."""
    tf_ledger = VirtualLedger(initial_cash_idr=10_000_000.0, name="PRIMARY_TF")
    mr_ledger = VirtualLedger(initial_cash_idr=10_000_000.0, name="SHADOW_MR")

    router = OrderRouter(
        risk_gate=RiskGate(),
        virtual_ledger=tf_ledger,
        shadow_ledger=mr_ledger,
        capital_governor=CapitalGovernor(),
    )

    # 1. Route Trend-Following order (BTC/IDR)
    res_tf = await router.route_buy_order(
        symbol="BTC/IDR",
        price=1_000_000_000.0,
        notional_idr=3_000_000.0,
        max_hold_time_s=21 * 86400.0,
        strategy="TREND_FOLLOWING",
    )
    assert res_tf["success"] is True
    assert res_tf["mode"] == "PAPER_VIRTUAL_LEDGER"
    assert res_tf["ledger"] == "PRIMARY_TF"
    assert "BTC/IDR" in tf_ledger.open_positions
    assert "BTC/IDR" not in mr_ledger.open_positions

    # 2. Route Mean-Reversion order (ETH/IDR)
    res_mr = await router.route_buy_order(
        symbol="ETH/IDR",
        price=50_000_000.0,
        notional_idr=3_000_000.0,
        max_hold_time_s=10 * 86400.0,
        strategy="MEAN_REVERSION",
    )
    assert res_mr["success"] is True
    assert res_mr["mode"] == "PAPER_SHADOW_LEDGER"
    assert res_mr["ledger"] == "SHADOW_MR"
    assert "ETH/IDR" in mr_ledger.open_positions
    assert "ETH/IDR" not in tf_ledger.open_positions


@pytest.mark.anyio
async def test_mean_reversion_remains_in_shadow_mode_even_when_live_flag_set():
    """Verify Mean-Reversion is strictly guarded in shadow mode and cannot leak to live trading."""
    tf_ledger = VirtualLedger(initial_cash_idr=10_000_000.0, name="PRIMARY_TF")
    mr_ledger = VirtualLedger(initial_cash_idr=10_000_000.0, name="SHADOW_MR")

    router = OrderRouter(
        risk_gate=RiskGate(),
        virtual_ledger=tf_ledger,
        shadow_ledger=mr_ledger,
        capital_governor=CapitalGovernor(),
    )

    with patch.object(settings, "LIVE_TRADING_ENABLED", True):
        # MR order should still execute smoothly into shadow_ledger without raising PermissionError
        res_mr = await router.route_buy_order(
            symbol="AVAX/IDR",
            price=400_000.0,
            notional_idr=2_000_000.0,
            strategy="MEAN_REVERSION",
        )
        assert res_mr["success"] is True
        assert res_mr["mode"] == "PAPER_SHADOW_LEDGER"
        assert res_mr["ledger"] == "SHADOW_MR"
        assert "AVAX/IDR" in mr_ledger.open_positions

        # TF order under LIVE_TRADING_ENABLED=True should raise PermissionError (locked in Phase 1)
        with pytest.raises(PermissionError):
            await router.route_buy_order(
                symbol="BTC/IDR",
                price=1_000_000_000.0,
                notional_idr=2_000_000.0,
                strategy="TREND_FOLLOWING",
            )


def test_shadow_mr_readiness_evaluator_targets():
    """Verify shadow_mr_readiness_evaluator uses N>=20, PF>=1.25 while primary uses N>=30, PF>=1.50."""
    assert shadow_mr_readiness_evaluator.target_sample_size == 20
    assert shadow_mr_readiness_evaluator.target_profit_factor == 1.25
    assert shadow_mr_readiness_evaluator.name == "SHADOW_MR"

    assert live_readiness_evaluator.target_sample_size == 30
    assert live_readiness_evaluator.target_profit_factor == 1.50
    assert live_readiness_evaluator.name == "PRIMARY_TF"


def test_shadow_mr_readiness_evaluation_success_on_20_trades():
    """Verify shadow MR evaluator approves SIAP_SOFT_LAUNCH on 20 winning trades while TF still requires 30."""
    evaluator_mr = LiveReadinessEvaluator(
        target_sample_size=20,
        target_profit_factor=1.25,
        target_win_rate_pct=45.0,
        max_drawdown_limit_pct=8.0,
        target_calendar_days=10,
        name="SHADOW_MR",
    )

    # 20 trades, 12 wins / 8 losses (WR 60%, PF = 2.4, spanning 10 distinct days)
    trades = []
    base_time = 1788220800.0  # 2026-09-01
    for i in range(20):
        is_win = i < 12
        pnl = 30_000.0 if is_win else -15_000.0
        day_offset = (i % 10) * 86400
        trades.append({
            "realized_pnl_idr": pnl,
            "realized_pnl_pct": 2.0 if is_win else -1.0,
            "exit_time": base_time + day_offset,
        })

    eval_res_mr = evaluator_mr.evaluate_trades(
        trade_history=trades,
        current_equity_idr=10_240_000.0,
        peak_equity_idr=10_250_000.0,
        current_drawdown_pct=0.1,
    )

    # MR track passes because N=20 reached!
    assert eval_res_mr["all_passed"] is True
    assert eval_res_mr["verdict"] == "SIAP_SOFT_LAUNCH"

    # Primary TF evaluator on the exact same 20 trades should FAIL (sample size 20 < 30)
    eval_res_tf = live_readiness_evaluator.evaluate_trades(
        trade_history=trades,
        current_equity_idr=10_240_000.0,
        peak_equity_idr=10_250_000.0,
        current_drawdown_pct=0.1,
    )
    assert eval_res_tf["all_passed"] is False
    assert eval_res_tf["criteria"]["sample_size"]["passed"] is False


def test_durable_state_isolates_primary_and_shadow_ledger(tmp_path):
    """Verify DurableStateStore separates state buckets between PRIMARY_TF and SHADOW_MR."""
    store = DurableStateStore(state_file_path=tmp_path / "durable_state.json")

    # Record primary TF position
    store.record_position_change(
        change_type="OPEN",
        position_data={"symbol": "BTCIDR", "cost_idr": 3_000_000.0, "strategy": "TREND_FOLLOWING"},
        total_equity_idr=10_000_000.0,
        ledger_name="PRIMARY_TF",
    )

    # Record shadow MR position
    store.record_position_change(
        change_type="OPEN",
        position_data={"symbol": "ETHIDR", "cost_idr": 2_000_000.0, "strategy": "MEAN_REVERSION"},
        total_equity_idr=10_000_000.0,
        ledger_name="SHADOW_MR",
    )

    state = store.get_state()
    # Primary positions bucket
    assert "BTCIDR" in state["open_positions"]
    assert "ETHIDR" not in state["open_positions"]

    # Shadow MR positions bucket
    assert "ETHIDR" in state["shadow_mr_open_positions"]
    assert "BTCIDR" not in state["shadow_mr_open_positions"]
