"""
Unit tests for Directive D-07:
1. Cross-Market Emergency De-Risking Ratchet (is_flash_crash detection & SL tightening).
2. Stagnation Exit (Dead-Capital Protection for positions held >= 5 days with CI >= 65 and move <= 0.60%).
3. Automated 7-Day Performance & Equity Curve Logger (DailyPerformanceTracker).
"""
import os
import time
import tempfile
from pathlib import Path
import pytest

from ingestion.binance_tracker import BinanceLeadLagTracker
from executor.virtual_ledger import VirtualLedger
from storage.performance_tracker import DailyPerformanceTracker


def test_binance_lead_lag_is_flash_crash_trigger():
    """
    Tests that BinanceLeadLagTracker detects 5-minute flash crashes (<= -2.0%)
    and returns correct boolean, return value, and diagnostic reason.
    """
    tracker = BinanceLeadLagTracker()
    now = time.time()

    # Ingest historical prices: 5 mins ago BTC was 65,000, now dropped to 63,500 (-2.31%)
    tracker.update_ticker({"symbol": "BTCUSDT", "close": 65000.0, "ts": now - 300.0})
    tracker.update_ticker({"symbol": "BTCUSDT", "close": 63500.0, "ts": now})

    is_crash, ret_5m, reason = tracker.is_flash_crash("BTC/IDR", threshold_5m=-0.020)
    assert is_crash is True
    assert ret_5m == pytest.approx(-0.0231, rel=1e-2)
    assert "5m flash crash" in reason

    # Test stable scenario for ETH (dropped only -0.5%)
    tracker.update_ticker({"symbol": "ETHUSDT", "close": 3500.0, "ts": now - 300.0})
    tracker.update_ticker({"symbol": "ETHUSDT", "close": 3482.5, "ts": now})

    is_crash_eth, ret_eth, reason_eth = tracker.is_flash_crash("ETHIDR", threshold_5m=-0.020)
    assert is_crash_eth is False
    assert ret_eth == pytest.approx(-0.005, rel=1e-2)
    assert reason_eth == "STABLE"


def test_cross_market_emergency_derisking_ratchets_stop_loss():
    """
    Tests that when binance_mom_5m <= -2.0% is passed to update_market_price,
    VirtualLedger immediately ratchets Stop Loss to max(current_sl, current_price * 0.990)
    to protect against impending Indodax liquidity cascade.
    """
    ledger = VirtualLedger(initial_cash_idr=10_000_000.0, name="TEST_EMERGENCY")

    buy_res = ledger.place_paper_buy(
        symbol="BTC/IDR",
        price=1_000_000_000.0,
        notional_idr=2_500_000.0,
        stop_loss_pct=5.0, # SL initially at 950,000,000
        take_profit_pct=8.0,
        strategy="TREND_FOLLOWING",
    )
    assert buy_res["success"] is True
    pos = ledger.open_positions["BTC/IDR"]
    initial_sl = pos.stop_loss_price
    assert initial_sl < 960_000_000.0

    # Normal tick, stable Binance (mom = -0.003): SL should not change
    ledger.update_market_price("BTC/IDR", 995_000_000.0, binance_mom_5m=-0.003)
    assert pos.stop_loss_price == initial_sl

    # Flash crash on Binance: mom = -0.025 (-2.5%)
    # Current Indodax price is 990,000,000
    # Emergency SL should ratchet to 990,000,000 * 0.99 = 980,100,000 (> 950,000,000)
    ledger.update_market_price("BTC/IDR", 990_000_000.0, binance_mom_5m=-0.025)
    expected_emergency_sl = 990_000_000.0 * 0.990
    assert pos.stop_loss_price == expected_emergency_sl
    assert pos.stop_loss_price > initial_sl

    # Pullback continues and breaches emergency SL -> closes position safely
    res_exit = ledger.update_market_price("BTC/IDR", 979_000_000.0)
    assert "BTC/IDR" not in ledger.open_positions
    assert res_exit["exit_reason"] == "STOP_LOSS_BREACHED"
    # Loss was contained to ~ -2.1% instead of full -5.0%
    assert res_exit["realized_pnl_pct"] > -3.0


def test_stagnation_dead_capital_exit():
    """
    Tests that if a position has been held >= 5.0 days, Choppiness Index >= 65.0,
    and unrealized price move <= 0.60%, it exits under STAGNATION_DEAD_CAPITAL_EXIT
    to recycle locked capital into higher-velocity opportunities.
    """
    ledger = VirtualLedger(initial_cash_idr=10_000_000.0, name="TEST_STAGNATION")

    buy_res = ledger.place_paper_buy(
        symbol="ETH/IDR",
        price=40_000_000.0,
        notional_idr=2_500_000.0,
        stop_loss_pct=5.0,
        take_profit_pct=8.0,
        strategy="TREND_FOLLOWING",
    )
    assert buy_res["success"] is True
    pos = ledger.open_positions["ETH/IDR"]

    # 1. Day 2: Not enough days held (2.0d < 5.0d), even if choppy
    pos.entry_time = time.time() - (2.0 * 86400.0)
    res = ledger.update_market_price("ETH/IDR", 40_100_000.0, current_ci=70.0)
    assert res is None
    assert "ETH/IDR" in ledger.open_positions

    # 2. Day 6: Held 6 days, but CI is trending low (45.0 < 65.0) -> No stagnation exit
    pos.entry_time = time.time() - (6.0 * 86400.0)
    res = ledger.update_market_price("ETH/IDR", 40_100_000.0, current_ci=45.0)
    assert res is None
    assert "ETH/IDR" in ledger.open_positions

    # 3. Day 6: Held 6 days, CI is high (68.0 >= 65.0), but price is trending (+3.5% move > 0.60%) -> No stagnation exit
    trending_price = 40_000_000.0 * 1.035
    res = ledger.update_market_price("ETH/IDR", trending_price, current_ci=68.0)
    assert res is None
    assert "ETH/IDR" in ledger.open_positions

    # 4. Day 6: Held 6 days, CI is high (68.0 >= 65.0), and price is stagnant (+0.25% move <= 0.60%) -> Triggers STAGNATION_DEAD_CAPITAL_EXIT
    stagnant_price = 40_000_000.0 * 1.0025
    exit_res = ledger.update_market_price("ETH/IDR", stagnant_price, current_ci=68.0)
    assert "ETH/IDR" not in ledger.open_positions
    assert exit_res["exit_reason"] == "STAGNATION_DEAD_CAPITAL_EXIT"
    assert ledger.cash_idr > 9_500_000.0 # Capital freed and recycled


def test_daily_performance_tracker_snapshots_and_7d_summary():
    """
    Tests DailyPerformanceTracker:
    - Atomically records daily equity snapshots.
    - Accurately rolls up 7-day PnL, Win Rate, Profit Factor, and Drawdown.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "daily_performance.json"
        tracker = DailyPerformanceTracker(state_file_path=state_file)

        now = time.time()
        day_s = 86400.0

        # Simulate 7 days of snapshots
        mock_days = [
            ("2026-09-11", now - (6 * day_s), 10_000_000.0, 10_000_000.0, 0, 0.0),
            ("2026-09-12", now - (5 * day_s), 10_020_000.0, 7_500_000.0, 1, 20_000.0),
            ("2026-09-13", now - (4 * day_s), 10_050_000.0, 5_000_000.0, 2, 50_000.0),
            ("2026-09-14", now - (3 * day_s), 10_030_000.0, 5_000_000.0, 2, 30_000.0),
            ("2026-09-15", now - (2 * day_s), 10_080_000.0, 6_000_000.0, 1, 80_000.0),
            ("2026-09-16", now - (1 * day_s), 10_110_000.0, 4_000_000.0, 2, 110_000.0),
            ("2026-09-17", now, 10_150_000.0, 4_100_000.0, 2, 150_000.0),
        ]

        for date_str, ts, eq, cash, open_cnt, unrealized in mock_days:
            tracker.record_daily_snapshot(
                total_equity_idr=eq,
                cash_idr=cash,
                open_positions_count=open_cnt,
                unrealized_pnl_idr=unrealized,
                date_str=date_str,
            )
            tracker.snapshots[-1]["timestamp"] = ts # Override timestamp for accurate window simulation

        # Mock trade history: 2 wins (+80,000, +40,000) and 1 loss (-30,000)
        mock_trades = [
            {"closed_at": now - (3 * day_s), "realized_pnl_idr": 80_000.0},
            {"closed_at": now - (2 * day_s), "realized_pnl_idr": -30_000.0},
            {"closed_at": now - (1 * day_s), "realized_pnl_idr": 40_000.0},
        ]

        summary = tracker.get_7d_summary(current_equity_idr=10_150_000.0, trade_history=mock_trades, now_ts=now)

        assert summary["baseline_equity_idr"] == 10_000_000.0
        assert summary["current_equity_idr"] == 10_150_000.0
        assert summary["pnl_7d_idr"] == 150_000.0
        assert summary["pnl_7d_pct"] == 1.50 # +1.50%
        assert summary["trades_7d_count"] == 3
        assert summary["win_rate_7d_pct"] == pytest.approx(66.7, abs=0.1) # 2 wins / 3 trades
        # Gross profit = 120k, Gross loss = 30k -> Profit factor = 4.0
        assert summary["profit_factor_7d"] == 4.0
        assert len(summary["equity_curve"]) == 7

        # Test persistence reload
        reloaded = DailyPerformanceTracker(state_file_path=state_file)
        assert len(reloaded.snapshots) == 7
        assert reloaded.snapshots[-1]["date"] == "2026-09-17"
