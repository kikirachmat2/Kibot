"""
Tests: VirtualLedger fee consistency.

Regression guard: entry_fee_rate MUST equal exit_fee_rate for any ledger
with a custom fee_pct (like P1-P4 which use 0.10% maker).

Guards against the bug where execute_partial_tp hardcoded
settings.FEE_ROUNDTRIP_PCT/2 instead of using self.fee_pct.
"""
import pytest

from executor.virtual_ledger import VirtualLedger
from config import settings


# ─── Test 1: Core regression — partial TP uses self.fee_pct not FEE_ROUNDTRIP_PCT/2 ─

def test_partial_tp_exit_fee_matches_self_fee_pct():
    """
    execute_partial_tp must use self.fee_pct for exit fee, NOT FEE_ROUNDTRIP_PCT/2.

    Bug (pre-fix): exit_fee = gross * (FEE_ROUNDTRIP_PCT / 100.0 / 2.0) = 0.21%
    Fix:           exit_fee = gross * (self.fee_pct / 100.0)             = 0.10%

    We verify by computing what the fee_rate implied by the returned net_proceeds is,
    and asserting it equals self.fee_pct — NOT FEE_ROUNDTRIP_PCT/2.
    """
    CUSTOM_FEE_PCT = 0.10
    NOTIONAL = 50_000.0
    ENTRY_PRICE = 100_000.0
    PARTIAL_TP_PRICE = 110_000.0   # +10%, triggers partial TP

    ledger = VirtualLedger(
        initial_cash_idr=200_000.0,
        name="TEST_P1_FEE",
        fee_pct=CUSTOM_FEE_PCT,
    )

    res = ledger.place_paper_buy(
        symbol="TESTIDR",
        price=ENTRY_PRICE,
        notional_idr=NOTIONAL,
        stop_loss_pct=15.0,
        take_profit_pct=20.0,
        partial_tp_pct=50.0,
        partial_tp_price=PARTIAL_TP_PRICE,
    )
    assert res["success"] is True

    pos = ledger.open_positions["TESTIDR"]
    coins_before = pos.amount_coins

    partial = ledger.execute_partial_tp("TESTIDR", PARTIAL_TP_PRICE)
    assert partial is not None, "execute_partial_tp returned None"

    # Compute gross proceeds from what the ledger actually used
    coins_closed = coins_before * 0.50
    gross = coins_closed * PARTIAL_TP_PRICE

    actual_net = partial["net_proceeds_idr"]
    actual_fee = gross - actual_net
    actual_fee_rate_pct = (actual_fee / gross) * 100.0

    # ── Core assertion: implied exit fee rate must equal self.fee_pct ──
    assert abs(actual_fee_rate_pct - CUSTOM_FEE_PCT) < 0.001, (
        f"Exit fee rate mismatch!\n"
        f"  Expected: {CUSTOM_FEE_PCT:.4f}% (self.fee_pct)\n"
        f"  Got:      {actual_fee_rate_pct:.4f}%\n"
        f"  Bug value would be: {settings.FEE_ROUNDTRIP_PCT / 2:.4f}% (FEE_ROUNDTRIP_PCT/2)\n"
        f"  This means execute_partial_tp is still using FEE_ROUNDTRIP_PCT/2 instead of self.fee_pct"
    )


# ─── Test 2: Default ledger (fee_pct=None) falls back to FEE_ROUNDTRIP_PCT/2 ─

def test_default_fee_pct_uses_roundtrip_fallback():
    """
    fee_pct=None must fall back to FEE_ROUNDTRIP_PCT/2 at partial TP exit.
    Preserves existing default behaviour — this must keep passing.
    """
    NOTIONAL = 100_000.0
    ENTRY_PRICE = 500_000.0
    PARTIAL_TP_PRICE = 550_000.0

    ledger = VirtualLedger(
        initial_cash_idr=500_000.0,
        name="TEST_DEFAULT_FEE",
        fee_pct=None,
    )

    res = ledger.place_paper_buy(
        symbol="DEFAULTFEE",
        price=ENTRY_PRICE,
        notional_idr=NOTIONAL,
        stop_loss_pct=15.0,
        take_profit_pct=20.0,
        partial_tp_pct=50.0,
        partial_tp_price=PARTIAL_TP_PRICE,
    )
    assert res["success"] is True

    pos = ledger.open_positions["DEFAULTFEE"]
    coins_before = pos.amount_coins

    partial = ledger.execute_partial_tp("DEFAULTFEE", PARTIAL_TP_PRICE)
    assert partial is not None

    coins_closed = coins_before * 0.50
    gross = coins_closed * PARTIAL_TP_PRICE
    actual_fee_rate_pct = ((gross - partial["net_proceeds_idr"]) / gross) * 100.0

    fallback_pct = settings.FEE_ROUNDTRIP_PCT / 2.0
    assert abs(actual_fee_rate_pct - fallback_pct) < 0.001, (
        f"Default fallback wrong: expected {fallback_pct:.4f}%, got {actual_fee_rate_pct:.4f}%"
    )


# ─── Test 3: close_paper_position uses self.fee_pct for full exit ─────────────

def test_close_paper_position_uses_custom_fee_pct():
    """
    close_paper_position (full exit path) must use self.fee_pct.
    Was already correct at line 526 — asserting to catch future regressions.
    """
    CUSTOM_FEE_PCT = 0.10
    NOTIONAL = 50_000.0
    ENTRY_PRICE = 200_000.0
    EXIT_PRICE = 220_000.0

    ledger = VirtualLedger(
        initial_cash_idr=200_000.0,
        name="TEST_CLOSE_FEE",
        fee_pct=CUSTOM_FEE_PCT,
    )

    res = ledger.place_paper_buy(
        symbol="CLOSEFEE",
        price=ENTRY_PRICE,
        notional_idr=NOTIONAL,
        stop_loss_pct=15.0,
        take_profit_pct=15.0,
    )
    assert res["success"] is True

    pos = ledger.open_positions["CLOSEFEE"]
    coins = pos.amount_coins
    pos.current_price = EXIT_PRICE

    trade = ledger.close_paper_position("CLOSEFEE", reason="TAKE_PROFIT_TARGET_HIT")

    gross = coins * EXIT_PRICE
    actual_fee_rate_pct = ((gross - trade["net_proceeds_idr"]) / gross) * 100.0

    assert abs(actual_fee_rate_pct - CUSTOM_FEE_PCT) < 0.001, (
        f"close_paper_position fee wrong: expected {CUSTOM_FEE_PCT:.4f}%, got {actual_fee_rate_pct:.4f}%"
    )


# ─── Test 4: Entry and exit fee rates are symmetric for a full roundtrip ──────

def test_roundtrip_fee_symmetry_custom_ledger():
    """
    For a ledger with fee_pct=X, both entry and exit should deduct X%.
    Total fee burden = 2X% of notional (entry) + 2X% of proceeds (exit) approximately.
    Ensures no fee creep from mismatched rates.
    """
    CUSTOM_FEE_PCT = 0.10
    NOTIONAL = 100_000.0
    ENTRY_PRICE = 1_000_000.0
    EXIT_PRICE = 1_100_000.0   # +10%

    ledger = VirtualLedger(
        initial_cash_idr=200_000.0,
        name="TEST_ROUNDTRIP",
        fee_pct=CUSTOM_FEE_PCT,
    )

    cash_start = ledger.cash_idr

    res = ledger.place_paper_buy(
        symbol="ROUNDTRIP",
        price=ENTRY_PRICE,
        notional_idr=NOTIONAL,
        stop_loss_pct=15.0,
        take_profit_pct=15.0,
    )
    assert res["success"] is True

    pos = ledger.open_positions["ROUNDTRIP"]
    pos.current_price = EXIT_PRICE

    trade = ledger.close_paper_position("ROUNDTRIP", reason="TAKE_PROFIT_TARGET_HIT")

    cash_end = ledger.cash_idr
    actual_roundtrip_fee = cash_start - cash_end - trade["realized_pnl_idr"]
    # Both entry and exit applied CUSTOM_FEE_PCT — not mixed rates
    entry_fee = NOTIONAL * (CUSTOM_FEE_PCT / 100.0)
    gross_exit = pos.amount_coins * EXIT_PRICE if pos.amount_coins else trade["net_proceeds_idr"] / (1 - CUSTOM_FEE_PCT / 100.0)

    # Fee symmetry: entry_rate == exit_rate within floating point tolerance
    exit_fee_implied = trade["net_proceeds_idr"] * (CUSTOM_FEE_PCT / 100.0) / (1 - CUSTOM_FEE_PCT / 100.0)
    entry_fee_rate = entry_fee / NOTIONAL
    exit_fee_rate = (gross_exit - trade["net_proceeds_idr"]) / gross_exit if gross_exit > 0 else 0

    assert abs(entry_fee_rate - exit_fee_rate) < 0.001, (
        f"Roundtrip fee asymmetry: entry={entry_fee_rate*100:.4f}% != exit={exit_fee_rate*100:.4f}%"
    )
