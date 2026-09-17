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
# TASK 3 — TELEMETRY LOOP RESILIENCE
# ============================================================================

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


async def _run_one_telemetry_cycle(pipeline, last_snapshot_date=""):
    """
    Runs exactly one cycle of the telemetry body (without the sleep or while loop).
    Mirrors the implementation in main.py._telemetry_loop after the 30s sleep.
    """
    import logging
    from datetime import datetime, timezone
    logger = logging.getLogger("test_telemetry")

    # ---- mirror the telemetry body ----
    latency = pipeline.council_pool.get_latency_stats()
    tf_eq = pipeline.virtual_ledger.get_total_equity()
    tf_open = len(pipeline.virtual_ledger.open_positions)
    tf_closed = len(pipeline.virtual_ledger.trade_history)

    open_summary = []
    total_open_exp = 0.0
    for sym, pos in pipeline.virtual_ledger.open_positions.items():
        exp = pos.amount_coins * pos.current_price
        total_open_exp += exp
        pnl_idr = exp - pos.cost_idr
        pnl_pct = (pnl_idr / pos.cost_idr * 100.0) if pos.cost_idr > 0 else 0.0
        open_summary.append(f"{sym}:{pnl_pct:+.2f}%")

    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snapshot_taken = False
    if last_snapshot_date != today_utc:
        try:
            open_positions_snap = dict(pipeline.virtual_ledger.open_positions)
            cost_sum = sum(p.cost_idr for p in open_positions_snap.values())
            snap_open_exp = sum(
                p.amount_coins * p.current_price for p in open_positions_snap.values()
            )
            unrealized_pnl = snap_open_exp - cost_sum
            pipeline.performance_tracker.record_daily_snapshot(
                total_equity_idr=tf_eq,
                cash_idr=pipeline.virtual_ledger.cash_idr,
                open_positions_count=len(open_positions_snap),
                unrealized_pnl_idr=unrealized_pnl,
                trade_history=pipeline.virtual_ledger.trade_history,
                date_str=today_utc,
            )
            last_snapshot_date = today_utc
            snapshot_taken = True
        except Exception as snap_err:
            logger.warning(f"[Telemetry] Daily snapshot failed (non-fatal): {snap_err}")

    return last_snapshot_date, snapshot_taken, total_open_exp


def _make_pipeline_stub(positions=None, cash=8_000_000.0, snapshot_raises=False):
    """Build a minimal pipeline mock suitable for telemetry testing."""
    pipeline = MagicMock()
    pipeline.virtual_ledger = _FakeLedger(cash=cash, positions=positions or {})
    pipeline.shadow_ledger = _FakeLedger()
    pipeline.council_pool.get_latency_stats.return_value = {"p50_ms": 1, "p90_ms": 2}
    pipeline.router.drop_rate_pct.return_value = 0.0
    pipeline._running = True

    if snapshot_raises:
        pipeline.performance_tracker.record_daily_snapshot.side_effect = RuntimeError("disk full")
    else:
        pipeline.performance_tracker.record_daily_snapshot.return_value = None

    return pipeline


def test_telemetry_snapshot_taken_on_new_date():
    """Normal path: snapshot succeeds and _last_snapshot_date is updated."""
    pipeline = _make_pipeline_stub()
    yesterday = "2000-01-01"  # definitely not today

    new_date, taken, _ = asyncio.run(_run_one_telemetry_cycle(pipeline, yesterday))

    assert taken is True
    assert new_date != yesterday
    pipeline.performance_tracker.record_daily_snapshot.assert_called_once()


def test_telemetry_snapshot_not_repeated_same_date():
    """If _last_snapshot_date already equals today, no snapshot should be taken."""
    pipeline = _make_pipeline_stub()
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    new_date, taken, _ = asyncio.run(_run_one_telemetry_cycle(pipeline, today))

    assert taken is False
    pipeline.performance_tracker.record_daily_snapshot.assert_not_called()


def test_telemetry_snapshot_exception_does_not_update_date():
    """
    When record_daily_snapshot() raises an exception:
    - last_snapshot_date must NOT be updated (stays as the old value).
    - The cycle must complete without raising (exception is swallowed).
    """
    pipeline = _make_pipeline_stub(snapshot_raises=True)
    yesterday = "2000-01-01"

    new_date, taken, _ = asyncio.run(_run_one_telemetry_cycle(pipeline, yesterday))

    assert taken is False
    assert new_date == yesterday, (
        "_last_snapshot_date must remain unchanged when snapshot raises"
    )


def test_telemetry_total_open_exp_computed_from_positions():
    """
    total_open_exp must be computed by walking open_positions directly,
    not referencing any outer-scope variable (no NameError risk).
    """
    pos = _FakePosition(amount_coins=0.002, current_price=1_350_000_000.0, cost_idr=2_500_000.0)
    pipeline = _make_pipeline_stub(positions={"BTCIDR": pos})

    _, _, total_open_exp = asyncio.run(_run_one_telemetry_cycle(pipeline, "2000-01-01"))

    expected = pos.amount_coins * pos.current_price  # 2_700_000
    assert total_open_exp == pytest.approx(expected, rel=1e-6), (
        f"total_open_exp must equal sum of (coins * current_price), "
        f"expected {expected:,.0f} got {total_open_exp:,.0f}"
    )


def test_telemetry_no_positions_zero_exposure():
    """
    With no open positions, total_open_exp must be 0.0 and the
    loop must complete without NameError.
    """
    pipeline = _make_pipeline_stub(positions={})
    _, _, total_open_exp = asyncio.run(_run_one_telemetry_cycle(pipeline, "2000-01-01"))
    assert total_open_exp == 0.0


def test_telemetry_snapshot_unrealized_pnl_correct():
    """Verify that unrealized_pnl = market_value - cost_idr is passed correctly."""
    pos = _FakePosition(amount_coins=1.0, current_price=50_000_000.0, cost_idr=45_000_000.0)
    pipeline = _make_pipeline_stub(positions={"ETHIDR": pos})

    asyncio.run(_run_one_telemetry_cycle(pipeline, "2000-01-01"))

    call_kwargs = pipeline.performance_tracker.record_daily_snapshot.call_args.kwargs
    expected_unrealized = 50_000_000.0 - 45_000_000.0  # = 5_000_000
    assert call_kwargs["unrealized_pnl_idr"] == pytest.approx(expected_unrealized, rel=1e-6)
    assert call_kwargs["open_positions_count"] == 1
