import json
import os
import shutil
import tempfile
from pathlib import Path
import pytest

from Core.Intelligence.autonomous_director import AutonomousDirector
from Core.Intelligence.paper_trade_tracker import PaperTradeTracker, get_paper_trade_tracker
import Core.Intelligence.paper_trade_tracker as ptt
import Core.Intelligence.strategy_stats as ss_mod
import Core.Intelligence.autonomous_director as ad


@pytest.fixture
def clean_test_env(monkeypatch):
    """Setup an isolated temporary directory for state and clear cached trackers."""
    tmp_dir = Path(tempfile.mkdtemp())
    state_dir = tmp_dir / "state"
    history_dir = state_dir / "trade_history"
    orders_dir = state_dir / "orders"
    history_dir.mkdir(parents=True, exist_ok=True)
    orders_dir.mkdir(parents=True, exist_ok=True)

    # Populate 30 proven trades for PROVEN_STRAT to achieve Scorecard APPROVED verdict
    lines = [
        json.dumps({
            "state": "RECONCILED",
            "pair": "BTC/IDR",
            "strategy_id": "PROVEN_STRAT",
            "realized_pnl_pct": 4.0,
        })
        for _ in range(25)
    ]
    lines += [
        json.dumps({
            "state": "RECONCILED",
            "pair": "BTC/IDR",
            "strategy_id": "PROVEN_STRAT",
            "realized_pnl_pct": -1.0,
        })
        for _ in range(5)
    ]
    (history_dir / "2026-05-20.jsonl").write_text("\n".join(lines), encoding="utf-8")

    # Patch paper_trade_tracker module dirs & clear instances
    monkeypatch.setattr(ptt, "STATE_DIR", state_dir)
    monkeypatch.setattr(ptt, "PAPER_OPEN_DIR", state_dir / "paper_trades" / "open")
    monkeypatch.setattr(ptt, "TRADE_HISTORY_DIR", history_dir)
    ptt._tracker_instances.clear()

    # Patch strategy_stats module dirs & reset aggregator
    monkeypatch.setattr(ss_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(ss_mod, "TRADE_HISTORY_DIR", history_dir)
    monkeypatch.setattr(ss_mod, "ORDERS_DIR", orders_dir)
    monkeypatch.setattr(ss_mod, "_aggregator", ss_mod.StrategyStatsAggregator(ttl_seconds=0))

    # Patch autonomous_director capital governor check to read from test state_dir
    def mock_is_gov_blocked():
        gov_file = state_dir / "capital_governor.json"
        if gov_file.exists():
            try:
                data = json.loads(gov_file.read_text(encoding="utf-8"))
                if data.get("status") == "BLOCKED_WITH_REASON" or not data.get("allow_new_orders", True):
                    return True
            except Exception:
                pass
        return False
    monkeypatch.setattr(ad, "_is_capital_governor_blocked", mock_is_gov_blocked)

    def mock_is_gov_risk_locked():
        gov_file = state_dir / "capital_governor.json"
        if gov_file.exists():
            try:
                data = json.loads(gov_file.read_text(encoding="utf-8"))
                if data.get("circuit_breaker_tripped") or data.get("status") == "OVERALL_DRAWDOWN_BREAKER_TRIPPED" or data.get("global_hard_stop"):
                    return True
            except Exception:
                pass
        return False
    monkeypatch.setattr(ad, "_is_capital_governor_risk_locked", mock_is_gov_risk_locked)

    yield state_dir

    shutil.rmtree(tmp_dir, ignore_errors=True)
    ptt._tracker_instances.clear()


def test_approved_does_not_leak_into_shadow_variants(clean_test_env, monkeypatch):
    """Scenario 1: Candidate APPROVED does not leak into existing PAPER_ONLY variants."""
    monkeypatch.setenv("KIBOT_LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("KIBOT_TRADING_MODE", "paper")

    director = AutonomousDirector(market_regime="BULL")

    # Candidate 1: Has proven track record -> qualifies for APPROVED
    cand_approved = {
        "pair": "BTC/IDR",
        "symbol": "BTC/IDR",
        "strategy_id": "PROVEN_STRAT",
        "price_idr": 1000000000.0,
        "spread_pct": 0.001,
        "volume_ratio": 2.5,
        "leadlag_score": 0.85,
        "daily_volatility_pct": 0.03,
        "data_age_seconds": 1.0,
    }
    # Candidate 2: Unknown strategy / no track record -> gets capped at PAPER_ONLY (shadow)
    cand_shadow = {
        "pair": "ETH/IDR",
        "symbol": "ETH/IDR",
        "strategy_id": "UNKNOWN_STRAT",
        "price_idr": 50000000.0,
        "spread_pct": 0.001,
        "volume_ratio": 2.0,
        "leadlag_score": 0.70,
        "daily_volatility_pct": 0.03,
        "data_age_seconds": 1.0,
    }

    # Run cycle
    res = director.evaluate_cycle([cand_approved, cand_shadow])

    assert len(res["approved"]) == 1
    assert res["approved"][0]["pair"] == "BTC/IDR"
    assert len(res["shadow"]) == 1
    assert res["shadow"][0]["pair"] == "ETH/IDR"

    # Verify that existing variant trackers (e.g. CONSERVATIVE, DEFAULT) ONLY hold ETH/IDR (the shadow candidate)
    cons_tracker = get_paper_trade_tracker("CONSERVATIVE")
    cons_open = cons_tracker.get_open_paper_trades()
    cons_pairs = [t.get("pair") for t in cons_open]
    assert "BTC/IDR" not in cons_pairs, "APPROVED candidate BTC/IDR leaked into CONSERVATIVE tracker!"

    default_tracker = get_paper_trade_tracker("DEFAULT")
    default_open = default_tracker.get_open_paper_trades()
    default_pairs = [t.get("pair") for t in default_open]
    assert "BTC/IDR" not in default_pairs, "APPROVED candidate BTC/IDR leaked into DEFAULT tracker!"


def test_approved_shadow_recorded_when_live_disabled(clean_test_env, monkeypatch):
    """Scenario 2: When live trading is disabled, approved candidate is tracked in APPROVED shadow tracker."""
    monkeypatch.setenv("KIBOT_LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("KIBOT_TRADING_MODE", "paper")

    director = AutonomousDirector(market_regime="BULL")
    cand_approved = {
        "pair": "BTC/IDR",
        "symbol": "BTC/IDR",
        "strategy_id": "PROVEN_STRAT",
        "price_idr": 1000000000.0,
        "spread_pct": 0.001,
        "volume_ratio": 2.5,
        "leadlag_score": 0.85,
        "daily_volatility_pct": 0.03,
        "data_age_seconds": 1.0,
    }

    res = director.evaluate_cycle([cand_approved])

    # live_forward must be empty because live gate is off
    assert len(res["live_forward"]) == 0
    assert len(res["approved"]) == 1

    # APPROVED tracker must have recorded the trade
    app_tracker = get_paper_trade_tracker("APPROVED")
    app_open = app_tracker.get_open_paper_trades()
    assert len(app_open) == 1
    assert app_open[0]["pair"] == "BTC/IDR"
    assert app_open[0]["variant_id"] == "APPROVED"
    assert app_open[0]["entry_price_idr"] == 1000000000.0
    assert app_open[0]["take_profit_price"] == 1000000000.0 * 1.035
    assert app_open[0]["stop_loss_price"] == 1000000000.0 * 0.990


def test_approved_live_forward_when_live_enabled_and_healthy(clean_test_env, monkeypatch):
    """Scenario 3: When live trading is enabled and CapitalGovernor healthy, candidate goes to live_forward and NOT shadow."""
    monkeypatch.setenv("KIBOT_LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("KIBOT_TRADING_MODE", "live")

    # CapitalGovernor healthy state
    gov_file = clean_test_env / "capital_governor.json"
    gov_file.write_text(json.dumps({
        "status": "RECONCILED",
        "allow_new_orders": True,
    }), encoding="utf-8")

    director = AutonomousDirector(market_regime="BULL")
    cand_approved = {
        "pair": "BTC/IDR",
        "symbol": "BTC/IDR",
        "strategy_id": "PROVEN_STRAT",
        "price_idr": 1000000000.0,
        "spread_pct": 0.001,
        "volume_ratio": 2.5,
        "leadlag_score": 0.85,
        "daily_volatility_pct": 0.03,
        "data_age_seconds": 1.0,
    }

    res = director.evaluate_cycle([cand_approved])

    # Candidate must be forwarded to live executor
    assert len(res["live_forward"]) == 1
    assert res["live_forward"][0]["pair"] == "BTC/IDR"

    # APPROVED shadow tracker must NOT open a trade (no dual-tracking)
    app_tracker = get_paper_trade_tracker("APPROVED")
    app_open = app_tracker.get_open_paper_trades()
    assert len(app_open) == 0, "Candidate was double-tracked in shadow tracker despite live execution active!"


def test_approved_shadow_recorded_when_capital_governor_blocked(clean_test_env, monkeypatch):
    """Scenario 4: When live trading is enabled but CapitalGovernor is blocked, candidate is tracked in APPROVED shadow."""
    monkeypatch.setenv("KIBOT_LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("KIBOT_TRADING_MODE", "live")

    # CapitalGovernor blocked state (e.g. zero balance or daily loss)
    gov_file = clean_test_env / "capital_governor.json"
    gov_file.write_text(json.dumps({
        "status": "BLOCKED_WITH_REASON",
        "allow_new_orders": False,
        "reason": "daily_loss_limit_reached",
    }), encoding="utf-8")

    director = AutonomousDirector(market_regime="BULL")
    cand_approved = {
        "pair": "BTC/IDR",
        "symbol": "BTC/IDR",
        "strategy_id": "PROVEN_STRAT",
        "price_idr": 1000000000.0,
        "spread_pct": 0.001,
        "volume_ratio": 2.5,
        "leadlag_score": 0.85,
        "daily_volatility_pct": 0.03,
        "data_age_seconds": 1.0,
    }

    res = director.evaluate_cycle([cand_approved])

    # Candidate is tracked in APPROVED shadow because CapitalGovernor blocked live execution
    app_tracker = get_paper_trade_tracker("APPROVED")
    app_open = app_tracker.get_open_paper_trades()
    assert len(app_open) == 1
    assert app_open[0]["pair"] == "BTC/IDR"
    assert app_open[0]["variant_id"] == "APPROVED"


def test_approved_shadow_blocked_when_capital_governor_circuit_breaker_tripped(clean_test_env, monkeypatch):
    """Scenario 5: When CapitalGovernor trips the circuit breaker (18%), APPROVED shadow tracker also halts new trades."""
    monkeypatch.setenv("KIBOT_LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("KIBOT_TRADING_MODE", "paper")

    # CapitalGovernor circuit breaker tripped
    gov_file = clean_test_env / "capital_governor.json"
    gov_file.write_text(json.dumps({
        "status": "OVERALL_DRAWDOWN_BREAKER_TRIPPED",
        "allow_new_orders": False,
        "circuit_breaker_tripped": True,
        "circuit_breaker_reason": "overall_drawdown_breaker_tripped (19.2% >= 18.0%)",
    }), encoding="utf-8")

    director = AutonomousDirector(market_regime="BULL")
    cand_approved = {
        "pair": "BTC/IDR",
        "symbol": "BTC/IDR",
        "strategy_id": "PROVEN_STRAT",
        "price_idr": 1000000000.0,
        "spread_pct": 0.001,
        "volume_ratio": 2.5,
        "leadlag_score": 0.85,
        "daily_volatility_pct": 0.03,
        "data_age_seconds": 1.0,
    }

    res = director.evaluate_cycle([cand_approved])

    # Candidate was approved by scorecard, BUT shadow tracking was halted by circuit breaker
    assert len(res["approved"]) == 1
    app_tracker = get_paper_trade_tracker("APPROVED")
    app_open = app_tracker.get_open_paper_trades()
    assert len(app_open) == 0, "APPROVED opened a trade despite CapitalGovernor circuit breaker tripped!"
