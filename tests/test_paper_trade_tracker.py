"""Unit tests for PaperTradeTracker and full end-to-end integration with StrategyStats Aggregator."""

import json
import time
from pathlib import Path
import pytest

from Core.Intelligence.paper_trade_tracker import PaperTradeTracker
from Core.Intelligence.strategy_stats import StrategyStatsAggregator
from Core.Intelligence.autonomous_director import AutonomousDirector


@pytest.fixture
def temp_paper_env(tmp_path, monkeypatch):
    import Core.Intelligence.paper_trade_tracker as ptt_mod
    import Core.Intelligence.strategy_stats as ss_mod

    state_dir = tmp_path / "state"
    open_dir = state_dir / "paper_trades" / "open"
    history_dir = state_dir / "trade_history"
    orders_dir = state_dir / "orders"

    open_dir.mkdir(parents=True, exist_ok=True)
    history_dir.mkdir(parents=True, exist_ok=True)
    orders_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(ptt_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(ptt_mod, "PAPER_OPEN_DIR", open_dir)
    monkeypatch.setattr(ptt_mod, "TRADE_HISTORY_DIR", history_dir)

    monkeypatch.setattr(ss_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(ss_mod, "TRADE_HISTORY_DIR", history_dir)
    monkeypatch.setattr(ss_mod, "ORDERS_DIR", orders_dir)

    tracker = PaperTradeTracker(open_dir=open_dir, history_dir=history_dir)
    aggregator = StrategyStatsAggregator(ttl_seconds=0)

    return tracker, aggregator, history_dir, open_dir


def test_full_paper_trade_lifecycle(temp_paper_env):
    tracker, aggregator, history_dir, open_dir = temp_paper_env

    # 1. Candidate gets PAPER_ONLY verdict
    shadow_candidate = {
        "symbol": "MOCK/IDR",
        "pair": "MOCK/IDR",
        "strategy_id": "MOMENTUM_TEST",
        "price_idr": 100.0,
        "scorecard_verdict": "PAPER_ONLY",
    }

    # 2. Open paper trade with calibrated TP=+3.5% / SL=-1.0%
    opened = tracker.open_paper_trade(shadow_candidate, budget_idr=10000.0, stop_loss_pct=0.010, take_profit_pct=0.035)
    assert opened is not None
    assert opened["pair"] == "MOCK/IDR"
    assert opened["entry_price_idr"] == 100.0
    assert len(tracker.get_open_paper_trades()) == 1

    # 3. Simulate market price move -> hits Take Profit target at 103.5 IDR (+3.5%)
    price_map = {"MOCK/IDR": 103.5}
    closed_list = tracker.evaluate_open_trades(price_map)

    assert len(closed_list) == 1
    closed = closed_list[0]
    assert closed["pair"] == "MOCK/IDR"
    assert closed["exit_reason"] == "TAKE_PROFIT_TARGET_HIT"
    assert closed["is_paper"] is True
    assert closed["realized_pnl_pct"] > 0.0  # Net profit after fee

    # Verify open trade file removed
    assert len(tracker.get_open_paper_trades()) == 0

    # 4. Verify paper trade history file written
    paper_files = list(history_dir.glob("paper_*.jsonl"))
    assert len(paper_files) == 1
    content = paper_files[0].read_text(encoding="utf-8")
    assert "MOCK/IDR" in content
    assert '"is_paper": true' in content.lower()

    # 5. Verify StrategyStatsAggregator reads the paper trade and updates sample size
    aggregator.refresh_if_needed(force=True)
    metrics, is_specific = aggregator.get_metrics_for_candidate(shadow_candidate)

    assert is_specific is True
    assert metrics.total_trades == 1
    assert metrics.sample_size_paper == 1
    assert metrics.sample_size_live == 0
    assert metrics.win_rate == 1.0


def test_autonomous_director_paper_trading_pipeline(temp_paper_env, monkeypatch):
    tracker, aggregator, history_dir, open_dir = temp_paper_env
    import Core.Intelligence.paper_trade_tracker as ptt_mod
    monkeypatch.setattr(ptt_mod, "_tracker_instances", {"DEFAULT": tracker, "CONSERVATIVE": tracker, "AGGRESSIVE": tracker})

    # Mock get_paper_trade_tracker inside director to use test tracker
    import Core.Intelligence.autonomous_director as ad_mod
    monkeypatch.setattr(ad_mod, "batch_evaluate_ev", lambda cands: cands)

    director = AutonomousDirector(market_regime="BULL")

    # Pass a shadow candidate
    cand = {
        "symbol": "SOL/IDR",
        "pair": "SOL/IDR",
        "price_idr": 1000.0,
        "spread_pct": 0.001,
        "volume_ratio": 1.5,
        "leadlag_score": 0.8,
        "daily_volatility_pct": 0.03,
        "data_age_seconds": 2.0,
        "strategy_id": "SOL_MOMENTUM",
        "is_specific_match": False,  # Will cause PAPER_ONLY cap
    }

    res = director.evaluate_cycle([cand], market_regime="BULL")
    assert len(res["shadow"]) == 1

    # Verify open paper trade created by director cycle
    open_trades = tracker.get_open_paper_trades()
    assert len(open_trades) == 1
    assert open_trades[0]["pair"] == "SOL/IDR"


def test_paper_trade_rr_ratio_safety_check(temp_paper_env):
    tracker, _, _, _ = temp_paper_env
    from Core.Intelligence.paper_trade_tracker import compute_net_rr_ratio, MIN_NET_RR_BUFFER

    # 1. Test default TP=+3.5% / SL=-1.0% net R:R ratio calculation
    default_net_rr = compute_net_rr_ratio(take_profit_pct=0.035, stop_loss_pct=0.01)
    assert default_net_rr >= MIN_NET_RR_BUFFER  # Must be >= 1.60 (actual: 1.63)

    cand = {"symbol": "TEST/IDR", "pair": "TEST/IDR", "price_idr": 100.0}

    # 2. Valid trade (TP=3.5%, SL=1%) opens successfully
    valid_trade = tracker.open_paper_trade(cand, take_profit_pct=0.035, stop_loss_pct=0.01)
    assert valid_trade is not None

    # 3. Invalid trade with bad R:R (TP=2%, SL=1.5% -> net RR ~0.84) must be blocked
    invalid_cand = {"symbol": "BAD/IDR", "pair": "BAD/IDR", "price_idr": 100.0}
    blocked_trade = tracker.open_paper_trade(invalid_cand, take_profit_pct=0.02, stop_loss_pct=0.015)
    assert blocked_trade is None


def test_paper_trade_exit_valuation_scenarios(temp_paper_env, monkeypatch):
    tracker, _, history_dir, _ = temp_paper_env
    cand = {"symbol": "VAL/IDR", "pair": "VAL/IDR", "price_idr": 100.0}
    
    # Open trade with 1 sec max hold
    trade = tracker.open_paper_trade(cand, take_profit_pct=0.035, stop_loss_pct=0.01, max_hold_seconds=0.1)
    assert trade is not None
    import time
    time.sleep(0.15)
    
    # Scenario A: Pair in price_map -> exit price taken from price_map
    closed_a = tracker.evaluate_open_trades({"VAL/IDR": 102.0})
    assert len(closed_a) == 1
    assert closed_a[0]["exit_price_idr"] == 102.0
    assert closed_a[0]["exit_reason"] == "MAX_HOLD_TIME_EXPIRED"
    assert closed_a[0]["is_invalid_valuation"] is False

    # Scenario B: Pair NOT in price_map, but HTTP fallback fetch succeeds
    trade_b = tracker.open_paper_trade(cand, take_profit_pct=0.035, stop_loss_pct=0.01, max_hold_seconds=0.1)
    time.sleep(0.15)

    class MockResp:
        status_code = 200
        def json(self):
            return {"ticker": {"last": 103.5}}

    import httpx
    monkeypatch.setattr(httpx, "get", lambda url, timeout=5.0: MockResp())
    closed_b = tracker.evaluate_open_trades({})  # Empty price_map
    assert len(closed_b) == 1
    assert closed_b[0]["exit_price_idr"] == 103.5
    assert closed_b[0]["exit_reason"] == "MAX_HOLD_TIME_EXPIRED"
    assert closed_b[0]["is_invalid_valuation"] is False

    # Scenario C: Pair NOT in price_map AND HTTP fallback fails -> Retry extension / Invalid valuation
    trade_c = tracker.open_paper_trade(cand, take_profit_pct=0.035, stop_loss_pct=0.01, max_hold_seconds=0.1)
    time.sleep(0.15)
    monkeypatch.setattr(httpx, "get", lambda url, timeout=5.0: (_ for _ in ()).throw(Exception("API Error")))
    
    # First call: Not hard expired yet (now < 2x max_hold), so expire_ts extended by 300s, trade remains open
    closed_c1 = tracker.evaluate_open_trades({})
    assert len(closed_c1) == 0
    open_c = tracker.get_open_paper_trades()
    assert len(open_c) == 1
    
    # Simulate reaching hard 2x limit
    open_c[0]["entry_time_ts"] = time.time() - 20000.0  # Far past
    open_c[0]["expire_ts"] = time.time() - 100.0
    tracker.open_dir.glob("*.json")
    for f in tracker.open_dir.glob("*.json"):
        import json
        d = json.loads(f.read_text())
        d["entry_time_ts"] = time.time() - 20000.0
        d["expire_ts"] = time.time() - 100.0
        f.write_text(json.dumps(d))

    closed_c2 = tracker.evaluate_open_trades({})
    assert len(closed_c2) == 1
    assert closed_c2[0]["exit_reason"] == "TIMEOUT_PRICE_UNAVAILABLE"
    assert closed_c2[0]["is_invalid_valuation"] is True


def test_paper_trade_stop_loss_exit_price(temp_paper_env):
    tracker, _, _, _ = temp_paper_env
    cand = {"symbol": "TESTSL/IDR", "pair": "TESTSL/IDR", "price_idr": 100.0}

    # Open trade with entry=100.0, stop_loss_pct=0.01 (-1.0%), so stop_loss_price = 99.0
    trade = tracker.open_paper_trade(cand, take_profit_pct=0.035, stop_loss_pct=0.01)
    assert trade is not None
    assert trade["stop_loss_price"] == 99.0

    # Force current_price = 98.5 (below stop_loss_price of 99.0)
    closed = tracker.evaluate_open_trades({"TESTSL/IDR": 98.5})
    assert len(closed) == 1
    assert closed[0]["exit_reason"] == "STOP_LOSS_BREACHED"
    # Verify exit_price_idr is EXACTLY 98.5 (current_price), which is strictly < entry_price_idr (100.0)
    assert closed[0]["exit_price_idr"] == 98.5
    assert closed[0]["exit_price_idr"] < closed[0]["entry_price_idr"]


def test_ai_assisted_variant_gate(monkeypatch, tmp_path):
    import Core.Intelligence.paper_trade_tracker as ptt_mod
    state_dir = tmp_path / "state"
    open_dir = state_dir / "paper_trades" / "ai_assisted" / "open"
    history_dir = state_dir / "trade_history"
    open_dir.mkdir(parents=True, exist_ok=True)
    history_dir.mkdir(parents=True, exist_ok=True)

    open_dir_gen = lambda var_id: state_dir / "paper_trades" / var_id.lower() / "open"
    ptt_mod._tracker_instances.clear()
    ai_tracker = ptt_mod.get_paper_trade_tracker("AI_ASSISTED")
    ai_tracker.open_dir = open_dir
    ai_tracker.history_dir = history_dir
    
    # Patch factory to return custom dirs
    def mock_get_tracker(var_id="DEFAULT"):
        key = (var_id or "DEFAULT").upper().strip()
        if key not in ptt_mod._tracker_instances:
            t = ptt_mod.PaperTradeTracker(variant_id=key, open_dir=open_dir if key == "AI_ASSISTED" else (state_dir / "paper_trades" / key.lower() / "open"), history_dir=history_dir)
            ptt_mod._tracker_instances[key] = t
        return ptt_mod._tracker_instances[key]

    monkeypatch.setattr(ptt_mod, "get_paper_trade_tracker", mock_get_tracker)

    director = AutonomousDirector()
    
    monkeypatch.setattr("Core.Intelligence.autonomous_director.run_scorecard", lambda c, market_regime=None: c.update({"scorecard_verdict": "PAPER_ONLY"}))
    monkeypatch.setattr("Core.Intelligence.autonomous_director.batch_evaluate_ev", lambda c: c)

    cand = {
        "symbol": "BTC/IDR",
        "pair": "BTC/IDR",
        "price_idr": 1000000000.0,
        "signal_quality": {"grade": "STRONG"},
        "volume_ratio": 2.5,
        "scorecard_verdict": "PAPER_ONLY",
    }

    from Core.Intelligence import kibot_ai_coordinator

    # 1. Mistral approve (confidence=85, no red flag) -> trade opened
    async def mock_ai_approve(*args, **kwargs):
        return {"confidence_score": 85, "has_red_flag": False, "reasoning": "Strong momentum"}

    monkeypatch.setattr(kibot_ai_coordinator, "query_ai", mock_ai_approve)
    res_approve = director.evaluate_cycle([cand])
    ai_tracker = ptt_mod.get_paper_trade_tracker("AI_ASSISTED")
    open_trades = ai_tracker.get_open_paper_trades()
    assert len(open_trades) == 1
    assert open_trades[0]["ai_confidence_score"] == 85

    # Clean open dir
    for f in open_dir.glob("*.json"):
        f.unlink()

    # 2. Mistral reject (confidence=30) -> trade skipped
    async def mock_ai_reject(*args, **kwargs):
        return {"confidence_score": 30, "has_red_flag": False, "reasoning": "Weak fundamental backdrop"}

    monkeypatch.setattr(kibot_ai_coordinator, "query_ai", mock_ai_reject)
    director.evaluate_cycle([cand])
    open_trades_rej = ai_tracker.get_open_paper_trades()
    assert len(open_trades_rej) == 0

    # 3. Mistral fails/timeout (fallback) -> trade skipped (fail-closed)
    async def mock_ai_fail(*args, **kwargs):
        return {"is_fallback": True}

    monkeypatch.setattr(kibot_ai_coordinator, "query_ai", mock_ai_fail)
    director.evaluate_cycle([cand])
    open_trades_fail = ai_tracker.get_open_paper_trades()
    assert len(open_trades_fail) == 0
