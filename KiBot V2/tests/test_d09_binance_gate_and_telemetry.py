"""
D-09 Regression Tests — Binance Gate Strict Allowlist (Task 2)
                       Telemetry Loop Resilience        (Task 3)

Task 2 — SwingEvaluator Binance gate (strict allowlist):
  - Only binance_data_status == "OK" (exact string) allows entry.
  - All other values must result in REJECTED / BINANCE_DATA_UNKNOWN.
  - Categories tested: UNKNOWN, STALE, ERROR, empty string, None,
    case variants, whitespace, typos.

Task 3 — _telemetry_loop snapshot semantics:
  - Snapshot succeeds normally → _last_snapshot_date updated.
  - Snapshot raises exception → loop continues, date NOT updated.
  - total_open_exp computed inline (no NameError from outer scope).
  - no reference to /health local variables.
"""
import asyncio
import time
import datetime
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from council.swing_evaluator import SwingEvaluator
from council.evaluator import CouncilDecision


# ============================================================================
# TASK 2 — BINANCE GATE STRICT ALLOWLIST
# ============================================================================

# Minimal valid TF candidate (all non-Binance conditions satisfied)
def _base_tf_candidate():
    return {
        "symbol": "BTC/IDR",
        "price": 1_050_000_000.0,
        "spread_pct": 0.001,
        "ema20": 1_020_000_000.0,
        "ema50": 980_000_000.0,
        "ema100": 920_000_000.0,
        "rsi14": 58.0,
        "atr14": 35_000_000.0,
        "volume": 150.0,
        "volume_sma20": 120.0,
        "choppiness_index": 45.0,
        "binance_momentum_1h": 0.005,
        "binance_is_dumping": False,
        # binance_data_status intentionally omitted or set per test
    }


@pytest.mark.parametrize("status", [
    "UNKNOWN",
    "STALE",
    "ERROR",
    "",
    "ok",            # wrong case
    "Ok",            # wrong case
    "OK ",           # trailing space
    " OK",           # leading space
    "OKAY",          # typo
    "TRUE",
    "1",
    "yes",
])
def test_binance_gate_rejects_all_non_ok_statuses(status):
    """
    Every value that is not exactly the string 'OK' must cause REJECTED
    with enrichment_status == 'BINANCE_DATA_UNKNOWN'.
    """
    evaluator = SwingEvaluator()
    cand = _base_tf_candidate()
    cand["binance_data_status"] = status

    decision = evaluator.evaluate(cand, bankroll_idr=10_000_000.0)

    assert decision.verdict == "REJECTED", (
        f"Expected REJECTED for binance_data_status={status!r}, "
        f"got {decision.verdict} ({decision.reason})"
    )
    assert decision.enrichment_status == "BINANCE_DATA_UNKNOWN", (
        f"Expected enrichment_status=BINANCE_DATA_UNKNOWN for status={status!r}"
    )
    assert status in decision.reason or "not 'OK'" in decision.reason


@pytest.mark.parametrize("status", [
    pytest.param(None, id="None_value"),
])
def test_binance_gate_rejects_none_status(status):
    """None value (missing key defaults to '') must also be rejected."""
    evaluator = SwingEvaluator()
    cand = _base_tf_candidate()
    # Store None; extract_indicator_values will convert via str() or default
    cand["binance_data_status"] = status

    decision = evaluator.evaluate(cand, bankroll_idr=10_000_000.0)

    assert decision.verdict == "REJECTED"
    assert decision.enrichment_status == "BINANCE_DATA_UNKNOWN"


def test_binance_gate_missing_key_defaults_to_rejected():
    """Candidate with NO binance_data_status key at all must be rejected."""
    evaluator = SwingEvaluator()
    cand = _base_tf_candidate()
    cand.pop("binance_data_status", None)   # ensure absent

    decision = evaluator.evaluate(cand, bankroll_idr=10_000_000.0)

    assert decision.verdict == "REJECTED"
    assert decision.enrichment_status == "BINANCE_DATA_UNKNOWN"


def test_binance_gate_ok_allows_entry():
    """Exactly 'OK' (uppercase, no whitespace) must allow entry when TF conditions met."""
    evaluator = SwingEvaluator()
    cand = _base_tf_candidate()
    cand["binance_data_status"] = "OK"

    decision = evaluator.evaluate(cand, bankroll_idr=10_000_000.0)

    assert decision.verdict == "APPROVED"
    assert decision.strategy == "TREND_FOLLOWING"


def test_binance_gate_mr_candidate_ok_allows_entry():
    """'OK' status also works for a valid MR candidate."""
    evaluator = SwingEvaluator()
    cand = {
        "symbol": "AVAX/IDR",
        "price": 380_000.0,
        "spread_pct": 0.002,
        "lower_bb": 390_000.0,
        "middle_bb": 420_000.0,
        "adx14": 18.5,
        "rsi14": 38.0,
        "sma20_slope": 0.005,
        "atr14": 15_000.0,
        "binance_momentum_1h": -0.01,
        "binance_data_status": "OK",
    }
    decision = evaluator.evaluate(cand, bankroll_idr=10_000_000.0)
    assert decision.verdict == "APPROVED"
    assert decision.strategy == "MEAN_REVERSION"


# ============================================================================
# TASK 3 — TELEMETRY LOOP RESILIENCE & PRODUCTION BINDING (D-10)
# ============================================================================
from main import KiBotV2Pipeline


class _FakePosition:
    """Minimal position stub for ledger mocking."""
    def __init__(self, amount_coins, current_price, cost_idr):
        self.amount_coins = amount_coins
        self.current_price = current_price
        self.cost_idr = cost_idr
        self.side = "BUY"
        self.entry_price = current_price
        self.stop_loss_price = current_price * 0.95
        self.take_profit_price = current_price * 1.08
        self.partial_tp_price = current_price * 1.04
        self.tp1_executed = False
        self.strategy = "TREND_FOLLOWING"


class _FakeLedger:
    """Minimal ledger stub."""
    def __init__(self, cash=8_000_000.0, positions=None, trade_history=None):
        self.cash_idr = cash
        self.open_positions = positions or {}
        self.trade_history = trade_history or []

    def get_total_equity(self):
        equity = self.cash_idr
        for pos in self.open_positions.values():
            equity += pos.amount_coins * pos.current_price
        return equity


async def _execute_one_telemetry_cycle(pipeline: KiBotV2Pipeline) -> list:
    """
    Executes exactly one iteration of the real KiBotV2Pipeline._telemetry_loop()
    production code.

    Deterministic termination:
    Inside the mocked asyncio.sleep(30), we record the sleep duration argument
    and immediately set pipeline._running = False. This allows the first cycle body
    to run to completion, after which the 'while self._running:' condition evaluates
    to False and the loop exits cleanly with zero sleep delay.
    """
    sleep_calls = []
    pipeline._running = True

    async def mock_sleep(seconds):
        sleep_calls.append(seconds)
        pipeline._running = False

    with patch("main.asyncio.sleep", side_effect=mock_sleep):
        await pipeline._telemetry_loop()

    return sleep_calls


def _make_pipeline_stub(positions=None, cash=8_000_000.0, snapshot_raises=False, last_snapshot_date=""):
    """
    Build a KiBotV2Pipeline instance with isolated components specifically
    for testing the production _telemetry_loop() without network or external I/O.
    """
    pipeline = KiBotV2Pipeline.__new__(KiBotV2Pipeline)
    pipeline._running = True
    pipeline._last_snapshot_date = last_snapshot_date
    pipeline.virtual_ledger = _FakeLedger(cash=cash, positions=positions or {})
    pipeline.shadow_ledger = _FakeLedger()
    pipeline.council_pool = MagicMock()
    pipeline.council_pool.get_latency_stats.return_value = {"p50_ms": 1, "p90_ms": 2}
    pipeline.router = MagicMock()
    pipeline.router.drop_rate_pct.return_value = 0.0
    pipeline.performance_tracker = MagicMock()

    if snapshot_raises:
        pipeline.performance_tracker.record_daily_snapshot.side_effect = RuntimeError("simulated disk full")
    else:
        pipeline.performance_tracker.record_daily_snapshot.return_value = None

    return pipeline


def test_telemetry_snapshot_taken_on_new_date():
    """
    Task 3A — Normal snapshot path using real KiBotV2Pipeline._telemetry_loop():
    - Date is different from today UTC
    - record_daily_snapshot() is called
    - _last_snapshot_date changes to today UTC
    """
    pipeline = _make_pipeline_stub(last_snapshot_date="2000-01-01")
    today_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    sleep_calls = asyncio.run(_execute_one_telemetry_cycle(pipeline))

    assert sleep_calls == [30]
    assert pipeline._last_snapshot_date == today_utc
    pipeline.performance_tracker.record_daily_snapshot.assert_called_once()
    kwargs = pipeline.performance_tracker.record_daily_snapshot.call_args.kwargs
    assert kwargs["date_str"] == today_utc
    assert kwargs["cash_idr"] == 8_000_000.0
    assert kwargs["total_equity_idr"] == 8_000_000.0


def test_telemetry_snapshot_not_repeated_same_date():
    """
    Task 3C — Same-date path using real KiBotV2Pipeline._telemetry_loop():
    - _last_snapshot_date == today UTC
    - record_daily_snapshot() is NOT called
    """
    today_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    pipeline = _make_pipeline_stub(last_snapshot_date=today_utc)

    sleep_calls = asyncio.run(_execute_one_telemetry_cycle(pipeline))

    assert sleep_calls == [30]
    assert pipeline._last_snapshot_date == today_utc
    pipeline.performance_tracker.record_daily_snapshot.assert_not_called()


def test_telemetry_snapshot_exception_does_not_update_date():
    """
    Task 3B — Snapshot failure path using real KiBotV2Pipeline._telemetry_loop():
    - record_daily_snapshot() raises Exception
    - _last_snapshot_date does NOT update (stays old value)
    - telemetry cycle completes without raising exception
    """
    old_date = "2000-01-01"
    pipeline = _make_pipeline_stub(snapshot_raises=True, last_snapshot_date=old_date)

    # Must complete without unhandled exception:
    sleep_calls = asyncio.run(_execute_one_telemetry_cycle(pipeline))

    assert sleep_calls == [30]
    assert pipeline._last_snapshot_date == old_date, (
        f"_last_snapshot_date must remain '{old_date}', got '{pipeline._last_snapshot_date}'"
    )
    pipeline.performance_tracker.record_daily_snapshot.assert_called_once()


def test_telemetry_total_open_exp_computed_from_positions(caplog):
    """
    Task 3D — Real _telemetry_loop() exposure calculation:
    - Fake open position
    - Verifies exposure is computed from amount_coins * current_price
    - Validates telemetry log formatting and snapshot unrealized PnL
    """
    pos = _FakePosition(amount_coins=0.002, current_price=1_350_000_000.0, cost_idr=2_500_000.0)
    expected_exp = 0.002 * 1_350_000_000.0  # = 2_700_000 IDR
    cash = 7_500_000.0
    total_eq = cash + expected_exp  # 10_200_000 IDR
    expected_exp_pct = (expected_exp / total_eq) * 100.0  # 26.470588% -> 26.5%

    pipeline = _make_pipeline_stub(positions={"BTCIDR": pos}, cash=cash)

    import logging
    with caplog.at_level(logging.INFO, logger="KiBotV2.Main"):
        asyncio.run(_execute_one_telemetry_cycle(pipeline))

    # 1. Verify snapshot received exact exposure and unrealized pnl
    pipeline.performance_tracker.record_daily_snapshot.assert_called_once()
    kwargs = pipeline.performance_tracker.record_daily_snapshot.call_args.kwargs
    assert kwargs["unrealized_pnl_idr"] == pytest.approx(expected_exp - 2_500_000.0, rel=1e-6)
    assert kwargs["open_positions_count"] == 1
    assert kwargs["total_equity_idr"] == pytest.approx(total_eq, rel=1e-6)

    # 2. Verify logger emitted the exact calculated exposure percentage
    assert f"Exp: {expected_exp_pct:.1f}%" in caplog.text
    assert "BTCIDR:+8.00%(Rp +200,000)" in caplog.text


def test_telemetry_no_positions_zero_exposure(caplog):
    """
    Task 3E — Real _telemetry_loop() with no open positions:
    - No positions in ledger
    - No NameError (e.g. from total_open_exp)
    - Exposure is 0.0%
    """
    pipeline = _make_pipeline_stub(positions={}, cash=10_000_000.0)

    import logging
    with caplog.at_level(logging.INFO, logger="KiBotV2.Main"):
        asyncio.run(_execute_one_telemetry_cycle(pipeline))

    pipeline.performance_tracker.record_daily_snapshot.assert_called_once()
    kwargs = pipeline.performance_tracker.record_daily_snapshot.call_args.kwargs
    assert kwargs["unrealized_pnl_idr"] == 0.0
    assert kwargs["open_positions_count"] == 0
    assert kwargs["total_equity_idr"] == pytest.approx(10_000_000.0, rel=1e-6)

    assert "Exp: 0.0%" in caplog.text
    assert "Open: 0" in caplog.text


def test_telemetry_snapshot_unrealized_pnl_correct():
    """
    Task 3 Additional: Verify unrealized_pnl = sum(market_val) - sum(cost)
    with multiple open positions in real _telemetry_loop().
    """
    pos1 = _FakePosition(amount_coins=1.0, current_price=50_000_000.0, cost_idr=45_000_000.0)
    pos2 = _FakePosition(amount_coins=0.01, current_price=1_000_000_000.0, cost_idr=11_000_000.0)
    pipeline = _make_pipeline_stub(positions={"ETHIDR": pos1, "BTCIDR": pos2}, cash=5_000_000.0)

    asyncio.run(_execute_one_telemetry_cycle(pipeline))

    pipeline.performance_tracker.record_daily_snapshot.assert_called_once()
    call_kwargs = pipeline.performance_tracker.record_daily_snapshot.call_args.kwargs
    expected_unrealized = (50_000_000.0 - 45_000_000.0) + (10_000_000.0 - 11_000_000.0)
    assert call_kwargs["unrealized_pnl_idr"] == pytest.approx(expected_unrealized, rel=1e-6)
    assert call_kwargs["open_positions_count"] == 2

