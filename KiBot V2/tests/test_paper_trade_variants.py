import pytest
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from paper_trade_runner import PaperTradeRunner, SPECS
from notifications.weekly_reporter import WeeklyReporter

@pytest.fixture
def temp_paper_runner(tmp_path):
    state_file = tmp_path / "paper_test_state.json"
    runner = PaperTradeRunner(state_file=state_file)
    return runner

def test_initial_state_and_specs(temp_paper_runner):
    runner = temp_paper_runner
    assert len(runner.ledgers) == 4
    for code in ("P1", "P2", "P3", "P4"):
        ledger = runner.ledgers[code]
        assert ledger.cash_idr == 100_000.0
        assert ledger.get_total_equity() == 100_000.0
        assert len(ledger.open_positions) == 0
        assert ledger.fee_pct == 0.10

def test_universe_filter(temp_paper_runner):
    runner = temp_paper_runner
    # Volume too low (< 100M)
    res_low_vol = runner.evaluate_candidate({
        "symbol": "TINYIDR",
        "price": 1000.0,
        "volume_idr": 50_000_000.0,
        "spread_pct": 0.002,
        "volume_ratio": 3.5,
    })
    assert res_low_vol["evaluated"] is False

    # Spread too wide (>= 0.5%)
    res_wide_spread = runner.evaluate_candidate({
        "symbol": "WIDEIDR",
        "price": 1000.0,
        "volume_idr": 200_000_000.0,
        "spread_pct": 0.008,
        "volume_ratio": 3.5,
    })
    assert res_wide_spread["evaluated"] is False

def test_p1_conservative_entry_and_tp(temp_paper_runner):
    runner = temp_paper_runner
    candidate = {
        "symbol": "BTCIDR",
        "price": 1_000_000_000.0,
        "volume_idr": 500_000_000.0,
        "spread_pct": 0.001,
        "leadlag_score": 0.3,
        "rsi14": 55.0,
        "ema20": 1_000_000_000.0,
        "ema50": 950_000_000.0,
        "volume_ratio": 1.2,
    }
    res = runner.evaluate_candidate(candidate)
    assert res["evaluated"] is True
    assert "P1" in res["orders"]
    p1_ledger = runner.ledgers["P1"]
    assert "BTCIDR" in p1_ledger.open_positions
    pos = p1_ledger.open_positions["BTCIDR"]
    assert pos.cost_idr == 50_000.0

    # Price triggers TP (+3%)
    tp_price = pos.entry_price * 1.031
    closed = runner.on_ticker("BTCIDR", tp_price)
    assert any(c.get("variant") == "P1" and c.get("exit_reason") == "TAKE_PROFIT_TARGET_HIT" for c in closed)
    assert "BTCIDR" not in p1_ledger.open_positions
    assert p1_ledger.cash_idr > 100_000.0

def test_p1_soft_exit_after_3_hours(temp_paper_runner):
    runner = temp_paper_runner
    candidate = {
        "symbol": "ETHIDR",
        "price": 50_000_000.0,
        "volume_idr": 500_000_000.0,
        "spread_pct": 0.001,
        "leadlag_score": 0.3,
        "rsi14": 55.0,
        "ema20": 50_000_000.0,
        "ema50": 48_000_000.0,
    }
    runner.evaluate_candidate(candidate)
    p1_ledger = runner.ledgers["P1"]
    pos = p1_ledger.open_positions["ETHIDR"]

    # Manipulate entry_time to be 3.5 hours ago
    pos.entry_time = time.time() - (3.5 * 3600.0)

    # Price drops by -5.5%
    loss_price = pos.entry_price * 0.945
    closed = runner.on_ticker("ETHIDR", loss_price)
    assert any(c.get("variant") == "P1" and c.get("exit_reason") == "SOFT_EXIT_3H_DRAWDOWN" for c in closed)
    assert "ETHIDR" not in p1_ledger.open_positions

def test_p4_vol_anomaly_filter(temp_paper_runner):
    runner = temp_paper_runner
    # Without volume spike (ratio = 1.5 < 3.0), P4 should NOT buy
    no_spike = {
        "symbol": "SOLOIDR",
        "price": 2_000_000.0,
        "volume_idr": 250_000_000.0,
        "spread_pct": 0.002,
        "volume_ratio": 1.5,
        "volume_projected_ratio": 1.5,
        "bollinger_pct_b": 0.5,
        "choppiness_index": 55.0,
    }
    res1 = runner.evaluate_candidate(no_spike)
    assert "P4" not in res1["orders"]

    # With volume spike (>3.0) and BB squeeze, P4 MUST buy
    spike = {
        "symbol": "SOLOIDR",
        "price": 2_000_000.0,
        "volume_idr": 250_000_000.0,
        "spread_pct": 0.002,
        "volume_ratio": 3.8,
        "volume_projected_ratio": 4.1,
        "bollinger_pct_b": 0.50,
        "choppiness_index": 55.0,
    }
    res2 = runner.evaluate_candidate(spike)
    assert "P4" in res2["orders"]
    assert "SOLOIDR" in runner.ledgers["P4"].open_positions

def test_max_two_positions_enforced(temp_paper_runner):
    runner = temp_paper_runner
    for sym in ("SYM1IDR", "SYM2IDR", "SYM3IDR"):
        runner.evaluate_candidate({
            "symbol": sym,
            "price": 1000.0,
            "volume_idr": 300_000_000.0,
            "spread_pct": 0.002,
            "leadlag_score": 0.3,
            "rsi14": 55.0,
            "volume_ratio": 2.0,
        })
    # Max positions is 2, so 3rd should be rejected
    for code, ledger in runner.ledgers.items():
        assert len(ledger.open_positions) <= 2

def test_weekly_reporter_message_format(tmp_path):
    reporter = WeeklyReporter(
        bot_token="fake-token",
        chat_id="fake-chat",
        reports_dir=tmp_path / "reports",
        start_date="2026-09-14",
    )
    fake_summary = {
        "P1": {"week_start_equity_idr": 100_000.0, "equity_idr": 102_500.0, "cum_pnl_idr": 2500.0},
        "P2": {"week_start_equity_idr": 100_000.0, "equity_idr": 104_000.0, "cum_pnl_idr": 4000.0},
        "P3": {"week_start_equity_idr": 100_000.0, "equity_idr": 98_000.0, "cum_pnl_idr": -2000.0},
        "P4": {"week_start_equity_idr": 100_000.0, "equity_idr": 105_000.0, "cum_pnl_idr": 5000.0},
        "P5": {"week_start_equity_idr": 100_000.0, "equity_idr": 103_000.0, "cum_pnl_idr": 3000.0, "regime": "BULL", "btc_dominance_trend_7h": 1.25},
    }
    msg = reporter.build_report_message(fake_summary)
    assert "📊 KiBOT V2 — LAPORAN HARI KE-" in msg
    assert "💰 Modal Awal Minggu: Rp 500.000" in msg
    assert "📈 PnL Hari Ini:" in msg
    assert "📊 PnL Kumulatif: +Rp 12.500 (+2.50%)" in msg
    assert "┌─ P1 Conservative: +Rp 2.500" in msg
    assert "├─ P2 Balanced: +Rp 4.000" in msg
    assert "├─ P3 Aggressive: -Rp 2.000" in msg
    assert "├─ P4 Vol Anomaly: +Rp 5.000" in msg
    assert "└─ P5 Rotation: +Rp 3.000" in msg
    assert "📊 REGIME SAAT INI: BULL | BTC.D Trend: +1.25%" in msg
    assert "🎯 Deadline:" in msg

    # Test snapshot save
    snap_path = reporter.save_snapshot(fake_summary, "2026-09-20")
    assert snap_path.exists()
