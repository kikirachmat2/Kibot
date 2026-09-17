"""
Unit and integration tests for Startup Reconciliation State Persistence.
Validates that restarting the bot (systemd, crash, deploy) mid-trade does NOT
corrupt or wipe open positions, cash, equity, or trade history for both
PRIMARY_TF (Trend-Following) and SHADOW_MR (Mean-Reversion) ledgers.
"""
import asyncio
import json
import time
import pytest
from pathlib import Path
from async_helper import run_async

from storage.durable_state import DurableStateStore
from storage.reconciler import StartupReconciler
from storage.live_readiness import LiveReadinessEvaluator
from executor.virtual_ledger import VirtualLedger, VirtualPosition

@run_async
async def test_mid_trade_restart_preserves_equity_and_positions(temp_data_dir):
    """
    Simulates opening TF (21-day hold) and MR (10-day hold) positions,
    closing one trade with profit, flushing to disk, then restarting the process.
    Verifies that open positions, cash, total equity, and trade history
    survive completely intact without data loss or equity drift.
    """
    state_file = temp_data_dir / "durable_state.json"
    store_before = DurableStateStore(state_file_path=state_file)
    await store_before.start()

    # Create evaluators
    tf_evaluator = LiveReadinessEvaluator(name="PRIMARY_TF")
    mr_evaluator = LiveReadinessEvaluator(name="SHADOW_MR", target_sample_size=20, target_profit_factor=1.25)

    # 1. Instantiate ledgers before restart
    tf_ledger_before = VirtualLedger(
        initial_cash_idr=10_000_000.0,
        name="PRIMARY_TF",
        readiness_evaluator=tf_evaluator,
    )
    mr_ledger_before = VirtualLedger(
        initial_cash_idr=10_000_000.0,
        name="SHADOW_MR",
        readiness_evaluator=mr_evaluator,
    )

    # 2. Execute a closed trade on PRIMARY_TF (win)
    # Buy SOL at 2,000,000 IDR (notional 2,000,000)
    import storage
    storage.durable_state.durable_state_store = store_before
    # Monkey-patch executor's store reference for test isolation
    import executor.virtual_ledger
    old_store = executor.virtual_ledger.durable_state_store
    executor.virtual_ledger.durable_state_store = store_before

    try:
        # Buy & close SOL with profit
        res_sol = tf_ledger_before.place_paper_buy(
            symbol="SOL/IDR",
            price=2_000_000.0,
            notional_idr=2_000_000.0,
            max_hold_time_s=21 * 86400.0,
            strategy="TREND_FOLLOWING",
        )
        assert res_sol["success"] is True
        # Close at 2,400,000 (+20%)
        tf_ledger_before.open_positions["SOL/IDR"].current_price = 2_400_000.0
        trade_sol = tf_ledger_before.close_paper_position("SOL/IDR", reason="TAKE_PROFIT_TARGET_HIT")
        assert trade_sol["realized_pnl_idr"] > 0

        # 3. Open mid-flight positions:
        # PRIMARY_TF: BTC/IDR, notional 3,000,000, hold 21 days
        res_btc = tf_ledger_before.place_paper_buy(
            symbol="BTC/IDR",
            price=1_000_000_000.0,
            notional_idr=3_000_000.0,
            max_hold_time_s=21 * 86400.0,
            strategy="TREND_FOLLOWING",
        )
        assert res_btc["success"] is True

        # SHADOW_MR: ETH/IDR, notional 2,000,000, hold 10 days
        res_eth = mr_ledger_before.place_paper_buy(
            symbol="ETH/IDR",
            price=50_000_000.0,
            notional_idr=2_000_000.0,
            max_hold_time_s=10 * 86400.0,
            strategy="MEAN_REVERSION",
        )
        assert res_eth["success"] is True

        # Record metrics right before crash
        tf_cash_pre = tf_ledger_before.cash_idr
        tf_equity_pre = tf_ledger_before.get_total_equity()
        tf_open_cnt_pre = len(tf_ledger_before.open_positions)
        tf_trades_cnt_pre = len(tf_ledger_before.trade_history)

        mr_cash_pre = mr_ledger_before.cash_idr
        mr_equity_pre = mr_ledger_before.get_total_equity()
        mr_open_cnt_pre = len(mr_ledger_before.open_positions)
        mr_trades_cnt_pre = len(mr_ledger_before.trade_history)

        # Allow background queue to flush and stop store
        await asyncio.sleep(0.05)
        await store_before.stop()

        # =========================================================================
        # 4. SIMULATE RESTART (e.g. systemd restart / deploy / crash)
        # =========================================================================
        store_after = DurableStateStore(state_file_path=state_file)
        executor.virtual_ledger.durable_state_store = store_after
        storage.durable_state.durable_state_store = store_after

        reconciler = StartupReconciler(state_store=store_after)
        reconcile_res = await reconciler.reconcile_on_startup()

        assert reconcile_res["reconciled"] is True
        assert "primary" in reconcile_res
        assert "shadow" in reconcile_res

        # Fresh ledgers after restart
        tf_ledger_after = VirtualLedger(
            initial_cash_idr=10_000_000.0,
            name="PRIMARY_TF",
            readiness_evaluator=tf_evaluator,
        )
        mr_ledger_after = VirtualLedger(
            initial_cash_idr=10_000_000.0,
            name="SHADOW_MR",
            readiness_evaluator=mr_evaluator,
        )

        # Apply state restoration (just like main.py does)
        primary_data = reconcile_res["primary"]
        tf_ledger_after.restore_state(
            cash_idr=primary_data.get("cash_idr"),
            open_positions_data=primary_data.get("open_positions"),
            trade_history_data=primary_data.get("closed_trades"),
            peak_equity_idr=primary_data.get("peak_equity_idr"),
        )

        shadow_data = reconcile_res["shadow"]
        mr_ledger_after.restore_state(
            cash_idr=shadow_data.get("cash_idr"),
            open_positions_data=shadow_data.get("open_positions"),
            trade_history_data=shadow_data.get("closed_trades"),
            peak_equity_idr=shadow_data.get("peak_equity_idr"),
        )

        # 5. VERIFY RECONCILIATION INTEGRITY:
        # A. Primary (TF) Ledger verification
        assert tf_ledger_after.cash_idr == pytest.approx(tf_cash_pre, abs=1.0)
        assert tf_ledger_after.get_total_equity() == pytest.approx(tf_equity_pre, abs=1.0)
        assert len(tf_ledger_after.open_positions) == tf_open_cnt_pre == 1
        assert len(tf_ledger_after.trade_history) == tf_trades_cnt_pre == 1
        assert "BTC/IDR" in tf_ledger_after.open_positions
        btc_pos = tf_ledger_after.open_positions["BTC/IDR"]
        assert isinstance(btc_pos, VirtualPosition)
        assert btc_pos.max_hold_time_s == 21 * 86400.0
        assert btc_pos.strategy == "TREND_FOLLOWING"
        assert btc_pos.cost_idr == 3_000_000.0

        # Trade history check (SOL trade restored)
        assert tf_ledger_after.trade_history[0]["symbol"] == "SOL/IDR"
        assert tf_ledger_after.trade_history[0]["realized_pnl_idr"] > 0

        # B. Shadow (MR) Ledger verification
        assert mr_ledger_after.cash_idr == pytest.approx(mr_cash_pre, abs=1.0)
        assert mr_ledger_after.get_total_equity() == pytest.approx(mr_equity_pre, abs=1.0)
        assert len(mr_ledger_after.open_positions) == mr_open_cnt_pre == 1
        assert "ETH/IDR" in mr_ledger_after.open_positions
        eth_pos = mr_ledger_after.open_positions["ETH/IDR"]
        assert isinstance(eth_pos, VirtualPosition)
        assert eth_pos.max_hold_time_s == 10 * 86400.0
        assert eth_pos.strategy == "MEAN_REVERSION"
        assert eth_pos.cost_idr == 2_000_000.0

        # 6. VERIFY LIFECYCLE EVALUATION ON RESTORED POSITIONS:
        # Advance time by 11 days (950,400s)
        # Test ETH (MR - 10 day max hold):
        # Setting simulated clock on pos.entry_time
        eth_pos.entry_time = time.time() - (11 * 86400.0)
        close_mr_res = mr_ledger_after.update_market_price("ETH/IDR", current_price=50_000_000.0)
        # Should close due to MAX_HOLD_TIME_EXPIRED (11d > 10d)
        assert close_mr_res is not None
        assert close_mr_res["exit_reason"] == "MAX_HOLD_TIME_EXPIRED"
        assert "ETH/IDR" not in mr_ledger_after.open_positions
        assert len(mr_ledger_after.trade_history) == 1

        # Test BTC (TF - 21 day max hold):
        # Same 11 days elapsed: BTC should NOT expire because 11d < 21d!
        btc_pos.entry_time = time.time() - (11 * 86400.0)
        stay_open_res = tf_ledger_after.update_market_price("BTC/IDR", current_price=1_000_000_000.0)
        assert stay_open_res is None
        assert "BTC/IDR" in tf_ledger_after.open_positions

        # Now advance BTC to 22 days elapsed:
        btc_pos.entry_time = time.time() - (22 * 86400.0)
        close_tf_res = tf_ledger_after.update_market_price("BTC/IDR", current_price=1_000_000_000.0)
        assert close_tf_res is not None
        assert close_tf_res["exit_reason"] == "MAX_HOLD_TIME_EXPIRED"
        assert "BTC/IDR" not in tf_ledger_after.open_positions
        assert len(tf_ledger_after.trade_history) == 2

    finally:
        executor.virtual_ledger.durable_state_store = old_store
        storage.durable_state.durable_state_store = old_store

@run_async
async def test_startup_reconciliation_handles_legacy_or_empty_state(temp_data_dir):
    """
    Verifies that reconciler handles brand-new or partial state files gracefully
    without raising KeyError or corrupting default initial 10M IDR balances.
    """
    empty_file = temp_data_dir / "non_existent_state.json"
    store = DurableStateStore(state_file_path=empty_file)
    reconciler = StartupReconciler(state_store=store)
    
    res = await reconciler.reconcile_on_startup()
    assert res["reconciled"] is True
    assert res["cash_idr"] == 10_000_000.0
    assert res["primary"]["cash_idr"] == 10_000_000.0
    assert res["shadow"]["cash_idr"] == 10_000_000.0
    assert res["primary"]["open_positions"] == {}
    assert res["shadow"]["open_positions"] == {}

    # Test restore_state on clean ledgers
    ledger = VirtualLedger(name="PRIMARY_TF")
    ledger.restore_state(
        cash_idr=res["primary"]["cash_idr"],
        open_positions_data=res["primary"]["open_positions"],
        trade_history_data=res["primary"]["closed_trades"],
        peak_equity_idr=res["primary"]["equity_idr"],
    )
    assert ledger.cash_idr == 10_000_000.0
    assert ledger.get_total_equity() == 10_000_000.0
    assert len(ledger.open_positions) == 0
    assert len(ledger.trade_history) == 0

@run_async
async def test_pipeline_startup_reconciliation(temp_data_dir):
    """
    Tests that KiBotV2Pipeline correctly restores both primary and shadow ledgers
    from durable state on process boot.
    """
    state_file = temp_data_dir / "durable_state.json"
    with open(state_file, "w") as f:
        json.dump({
            "version": "2.0.0",
            "cash_idr": 7_500_000.0,
            "equity_idr": 10_200_000.0,
            "open_positions": {
                "BTC/IDR": {
                    "symbol": "BTC/IDR",
                    "entry_price": 1_000_000_000.0,
                    "amount_coins": 0.0027,
                    "cost_idr": 2_700_000.0,
                    "strategy": "TREND_FOLLOWING",
                    "max_hold_time_s": 21 * 86400.0,
                }
            },
            "closed_trades": [
                {"symbol": "SOL/IDR", "realized_pnl_idr": 200_000.0, "exit_reason": "TAKE_PROFIT"}
            ],
            "shadow_mr_cash_idr": 8_000_000.0,
            "shadow_mr_equity_idr": 9_950_000.0,
            "shadow_mr_open_positions": {
                "ETH/IDR": {
                    "symbol": "ETH/IDR",
                    "entry_price": 50_000_000.0,
                    "amount_coins": 0.04,
                    "cost_idr": 2_000_000.0,
                    "strategy": "MEAN_REVERSION",
                    "max_hold_time_s": 10 * 86400.0,
                }
            },
            "shadow_mr_closed_trades": [
                {"symbol": "ADA/IDR", "realized_pnl_idr": 50_000.0, "exit_reason": "TAKE_PROFIT"}
            ],
        }, f)

    from main import KiBotV2Pipeline
    from storage.durable_state import DurableStateStore
    store = DurableStateStore(state_file_path=state_file)
    reconciler = StartupReconciler(state_store=store)

    pipeline = KiBotV2Pipeline()
    pipeline.reconciler = reconciler

    reconcile_res = await pipeline.reconciler.reconcile_on_startup()
    
    primary_data = reconcile_res.get("primary", {})
    pipeline.virtual_ledger.restore_state(
        cash_idr=primary_data.get("cash_idr"),
        open_positions_data=primary_data.get("open_positions"),
        trade_history_data=primary_data.get("closed_trades"),
        peak_equity_idr=primary_data.get("peak_equity_idr"),
    )

    shadow_data = reconcile_res.get("shadow", {})
    pipeline.shadow_ledger.restore_state(
        cash_idr=shadow_data.get("cash_idr"),
        open_positions_data=shadow_data.get("open_positions"),
        trade_history_data=shadow_data.get("closed_trades"),
        peak_equity_idr=shadow_data.get("peak_equity_idr"),
    )

    assert pipeline.virtual_ledger.cash_idr == 7_500_000.0
    assert "BTC/IDR" in pipeline.virtual_ledger.open_positions
    assert len(pipeline.virtual_ledger.trade_history) == 1
    assert pipeline.virtual_ledger.open_positions["BTC/IDR"].strategy == "TREND_FOLLOWING"
    assert pipeline.virtual_ledger.open_positions["BTC/IDR"].max_hold_time_s == 21 * 86400.0

    assert pipeline.shadow_ledger.cash_idr == 8_000_000.0
    assert "ETH/IDR" in pipeline.shadow_ledger.open_positions
    assert len(pipeline.shadow_ledger.trade_history) == 1
    assert pipeline.shadow_ledger.open_positions["ETH/IDR"].strategy == "MEAN_REVERSION"
    assert pipeline.shadow_ledger.open_positions["ETH/IDR"].max_hold_time_s == 10 * 86400.0

