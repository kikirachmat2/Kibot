import json
import pytest
from pathlib import Path
from Core.Intelligence.paper_trade_tracker import PaperTradeTracker
from Core.Intelligence.strategy_stats import StrategyStatsAggregator


@pytest.fixture
def temp_circuit_breaker_env(tmp_path, monkeypatch):
    open_dir = tmp_path / "state" / "paper_open"
    history_dir = tmp_path / "state" / "trade_history"
    state_dir = tmp_path / "state"
    open_dir.mkdir(parents=True, exist_ok=True)
    history_dir.mkdir(parents=True, exist_ok=True)

    import Core.Intelligence.paper_trade_tracker as ptt_mod
    monkeypatch.setattr(ptt_mod, "STATE_DIR", state_dir)

    tracker = PaperTradeTracker(open_dir=open_dir, history_dir=history_dir, bankroll_idr=10_000_000.0)
    return tracker, state_dir, open_dir, history_dir


def test_leadlag_candidate_without_price_idr_is_rejected(temp_circuit_breaker_env):
    """Verifies that LEADLAG_ALPHA candidates without explicit price_idr (e.g. only yield %) are rejected."""
    tracker, state_dir, open_dir, history_dir = temp_circuit_breaker_env

    # 1. Corrupted/Legacy candidate with only expected_net_pct mapped to 'price' (no price_idr)
    corrupted_cand = {
        "symbol": "BTC/IDR",
        "pair": "BTC/IDR",
        "source": "LEADLAG_ALPHA",
        "price": 4.422,  # Yield percentage mistakenly put in generic price
        "opportunity_score": 75.0,
        "confidence": 0.85,
        "scorecard_verdict": "PAPER_ONLY",
    }

    opened = tracker.open_paper_trade(corrupted_cand, budget_idr=250000.0, stop_loss_pct=0.010, take_profit_pct=0.035)
    assert opened is None, "Candidate without price_idr must be rejected"
    assert len(tracker.get_open_paper_trades()) == 0, "No open position should be created"

    # 2. Valid candidate with explicit positive price_idr
    valid_cand = {
        "symbol": "BTC/IDR",
        "pair": "BTC/IDR",
        "source": "LEADLAG_ALPHA",
        "price_idr": 1_150_000_000.0,
        "opportunity_score": 75.0,
        "confidence": 0.85,
        "scorecard_verdict": "PAPER_ONLY",
    }

    opened_valid = tracker.open_paper_trade(valid_cand, budget_idr=250000.0, stop_loss_pct=0.010, take_profit_pct=0.035)
    assert opened_valid is not None, "Candidate with valid price_idr must be accepted"
    assert opened_valid["entry_price_idr"] == 1_150_000_000.0
    assert len(tracker.get_open_paper_trades()) == 1


def test_absurd_positive_pnl_circuit_breaker(temp_circuit_breaker_env):
    """Verifies that an absurd PnL (>500%) is flagged as is_invalid_valuation=True and excluded from equity."""
    tracker, state_dir, open_dir, history_dir = temp_circuit_breaker_env

    candidate = {
        "symbol": "BTC/IDR",
        "pair": "BTC/IDR",
        "price_idr": 100.0,  # low entry
        "scorecard_verdict": "PAPER_ONLY",
    }

    trade = tracker.open_paper_trade(candidate, budget_idr=250000.0)
    assert trade is not None

    # Simulate exit at 1,000,000 IDR (astronomical gain > 500%)
    closed = tracker.close_paper_trade(trade, exit_price=1_000_000.0, exit_reason="TAKE_PROFIT_TARGET_HIT")

    assert closed["is_invalid_valuation"] is True, "Trade with >500% PnL must be flagged as is_invalid_valuation=True"
    assert closed["realized_pnl_pct"] > 500.0

    # Verify equity accumulator file was NOT polluted
    equity_file = state_dir / "paper_equity.json"
    if equity_file.exists():
        eq_data = json.loads(equity_file.read_text(encoding="utf-8"))
        assert eq_data.get("total_pnl_idr", 0.0) == 0.0, "Corrupted PnL must NOT be added to total_pnl_idr"
        assert eq_data.get("current_equity_idr") == 10_000_000.0, "Bankroll must remain intact"


def test_absurd_negative_pnl_circuit_breaker(temp_circuit_breaker_env):
    """Verifies that an absurd loss (<-100%) is flagged and excluded from equity."""
    tracker, state_dir, open_dir, history_dir = temp_circuit_breaker_env

    candidate = {
        "symbol": "SOL/IDR",
        "pair": "SOL/IDR",
        "price_idr": 1000.0,
        "scorecard_verdict": "PAPER_ONLY",
    }

    trade = tracker.open_paper_trade(candidate, budget_idr=250000.0)
    assert trade is not None

    # Force an impossible negative exit price causing <-100% net loss
    closed = tracker.close_paper_trade(trade, exit_price=-500.0, exit_reason="STOP_LOSS_BREACHED")

    assert closed["is_invalid_valuation"] is True
    assert closed["realized_pnl_pct"] < -100.0

    equity_file = state_dir / "paper_equity.json"
    if equity_file.exists():
        eq_data = json.loads(equity_file.read_text(encoding="utf-8"))
        assert eq_data.get("total_pnl_idr", 0.0) == 0.0


def test_normal_pnl_updates_equity_correctly(temp_circuit_breaker_env):
    """Verifies that normal trades (<500% PnL) properly update the equity accumulator."""
    tracker, state_dir, open_dir, history_dir = temp_circuit_breaker_env

    candidate = {
        "symbol": "ETH/IDR",
        "pair": "ETH/IDR",
        "price_idr": 50_000_000.0,
        "scorecard_verdict": "PAPER_ONLY",
    }

    trade = tracker.open_paper_trade(candidate, budget_idr=250000.0)
    assert trade is not None

    # Normal profit: exit at +3% (51,500,000 IDR)
    closed = tracker.close_paper_trade(trade, exit_price=51_500_000.0, exit_reason="TAKE_PROFIT_TARGET_HIT")

    assert closed["is_invalid_valuation"] is False
    assert 0 < closed["realized_pnl_pct"] < 500.0

    equity_file = state_dir / "paper_equity.json"
    assert equity_file.exists()
    eq_data = json.loads(equity_file.read_text(encoding="utf-8"))
    assert eq_data["total_paper_trades"] == 1
    assert eq_data["winning_trades"] == 1
    assert eq_data["total_pnl_idr"] > 0
    assert eq_data["current_equity_idr"] > 10_000_000.0
