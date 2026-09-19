"""
Tests: VirtualLedger asymmetric fee model.

Indodax IDR Market PRO uses ASYMMETRIC fees:
  BUY  maker=0.1111%  taker=0.2111%  (no PPh on buy)
  SELL maker=0.3211%  taker=0.4211%  (PPh 0.21% on sell)

Regression guards:
1. Entry uses buy_fee_pct (0.1111%), not sell rate.
2. Patient exits (TP, soft) use sell_maker_fee_pct (0.3211%).
3. Urgent exits (SL, max hold) use sell_taker_fee_pct (0.4211%).
4. Roundtrip is ASYMMETRIC: buy_fee != sell_fee.
5. trade_record contains exit_order_type for auditability.
"""
import pytest
from config.fees import IDR_BUY_FEES, IDR_SELL_FEES, URGENT_EXIT_REASONS, PATIENT_EXIT_REASONS
from executor.virtual_ledger import VirtualLedger


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_ledger(**kwargs) -> VirtualLedger:
    defaults = dict(initial_cash_idr=500_000.0, name="TEST")
    defaults.update(kwargs)
    return VirtualLedger(**defaults)


def _open(ledger, symbol, price, notional, **kw):
    r = ledger.place_paper_buy(
        symbol=symbol, price=price, notional_idr=notional,
        stop_loss_pct=15.0, take_profit_pct=20.0, **kw
    )
    assert r["success"], f"place_paper_buy failed: {r}"
    return r


def _fee_rate_from_net(gross, net):
    """Back-calculate the effective fee rate% from gross and net."""
    return ((gross - net) / gross) * 100.0


# ─── Test 1: Entry uses buy_fee_pct (BUY MAKER = 0.1111%) ────────────────────

def test_entry_uses_buy_maker_fee():
    """Entry must use IDR_BUY_FEES.maker_pct, not sell rates."""
    NOTIONAL = 100_000.0
    ENTRY_PRICE = 500_000.0

    ledger = _make_ledger()  # defaults: IDR_BUY_FEES + IDR_SELL_FEES
    _open(ledger, "BTCIDR", ENTRY_PRICE, NOTIONAL)

    pos = ledger.open_positions["BTCIDR"]
    # coins = (notional - entry_fee) / entry_price_with_slippage
    # entry_fee = NOTIONAL * buy_fee_pct/100
    entry_fee = NOTIONAL * (IDR_BUY_FEES.maker_pct / 100.0)
    expected_notional_after_fee = NOTIONAL - entry_fee
    # entry_price includes 0.1% slippage
    actual_cost_in_coins = pos.amount_coins * pos.entry_price
    assert abs(actual_cost_in_coins - expected_notional_after_fee) < 100.0, (
        f"Entry fee wrong: coins*price={actual_cost_in_coins:.2f}, "
        f"expected after buy_fee={expected_notional_after_fee:.2f}"
    )
    assert ledger.buy_fee_pct == IDR_BUY_FEES.maker_pct, (
        f"buy_fee_pct should be {IDR_BUY_FEES.maker_pct}, got {ledger.buy_fee_pct}"
    )


# ─── Test 2: Patient exit (TP) uses sell_maker_fee_pct (0.3211%) ──────────────

def test_patient_exit_tp_uses_sell_maker_fee():
    """TAKE_PROFIT_TARGET_HIT is a patient exit — must use sell_maker_fee_pct."""
    NOTIONAL = 100_000.0
    ENTRY_PRICE = 1_000_000.0
    EXIT_PRICE = 1_200_000.0

    ledger = _make_ledger()
    _open(ledger, "ETHIDR", ENTRY_PRICE, NOTIONAL)
    pos = ledger.open_positions["ETHIDR"]
    pos.current_price = EXIT_PRICE

    trade = ledger.close_paper_position("ETHIDR", reason="TAKE_PROFIT_TARGET_HIT")

    gross = pos.amount_coins * EXIT_PRICE
    actual_rate = _fee_rate_from_net(gross, trade["net_proceeds_idr"])

    assert abs(actual_rate - IDR_SELL_FEES.maker_pct) < 0.001, (
        f"TP exit fee wrong: expected {IDR_SELL_FEES.maker_pct:.4f}% (sell_maker), "
        f"got {actual_rate:.4f}%"
    )
    assert trade["exit_order_type"] == "maker"
    assert trade["exit_fee_pct_applied"] == pytest.approx(IDR_SELL_FEES.maker_pct, abs=0.001)


# ─── Test 3: Urgent exit (SL) uses sell_taker_fee_pct (0.4211%) ───────────────

def test_urgent_exit_sl_uses_sell_taker_fee():
    """STOP_LOSS_BREACHED is an urgent exit — must use sell_taker_fee_pct."""
    NOTIONAL = 100_000.0
    ENTRY_PRICE = 1_000_000.0
    SL_PRICE = 850_000.0

    ledger = _make_ledger()
    _open(ledger, "SOLIDR", ENTRY_PRICE, NOTIONAL)
    pos = ledger.open_positions["SOLIDR"]
    pos.current_price = SL_PRICE

    trade = ledger.close_paper_position("SOLIDR", reason="STOP_LOSS_BREACHED")

    gross = pos.amount_coins * SL_PRICE
    actual_rate = _fee_rate_from_net(gross, trade["net_proceeds_idr"])

    assert abs(actual_rate - IDR_SELL_FEES.taker_pct) < 0.001, (
        f"SL exit fee wrong: expected {IDR_SELL_FEES.taker_pct:.4f}% (sell_taker), "
        f"got {actual_rate:.4f}%"
    )
    assert trade["exit_order_type"] == "taker"
    assert trade["exit_fee_pct_applied"] == pytest.approx(IDR_SELL_FEES.taker_pct, abs=0.001)


# ─── Test 4: All urgent exit reasons use taker ────────────────────────────────

@pytest.mark.parametrize("reason", sorted(URGENT_EXIT_REASONS))
def test_all_urgent_exits_use_taker(reason):
    ledger = _make_ledger()
    _open(ledger, "ADAIDR", 1000.0, 50_000.0)
    pos = ledger.open_positions["ADAIDR"]
    pos.current_price = 900.0
    trade = ledger.close_paper_position("ADAIDR", reason=reason)
    assert trade["exit_order_type"] == "taker", f"{reason} should use taker"


# ─── Test 5: All patient exit reasons use maker ───────────────────────────────

@pytest.mark.parametrize("reason", sorted(PATIENT_EXIT_REASONS))
def test_all_patient_exits_use_maker(reason):
    ledger = _make_ledger()
    _open(ledger, "XRPIDR", 5000.0, 50_000.0)
    pos = ledger.open_positions["XRPIDR"]
    pos.current_price = 5200.0
    trade = ledger.close_paper_position("XRPIDR", reason=reason)
    assert trade["exit_order_type"] == "maker", f"{reason} should use maker"


# ─── Test 6: Roundtrip IS ASYMMETRIC (buy != sell) ───────────────────────────

def test_roundtrip_is_asymmetric():
    """
    BUY side fee (0.1111%) must NOT equal SELL side fee (0.3211% maker / 0.4211% taker).
    This replaces the old test_roundtrip_fee_symmetry_custom_ledger which encoded
    the WRONG assumption that entry_rate == exit_rate.
    """
    ledger = _make_ledger()
    assert ledger.buy_fee_pct != ledger.sell_maker_fee_pct, (
        f"buy_fee_pct ({ledger.buy_fee_pct}) should differ from "
        f"sell_maker_fee_pct ({ledger.sell_maker_fee_pct}) — asymmetric PPh on sell"
    )
    assert ledger.buy_fee_pct != ledger.sell_taker_fee_pct, (
        f"buy_fee_pct ({ledger.buy_fee_pct}) should differ from "
        f"sell_taker_fee_pct ({ledger.sell_taker_fee_pct})"
    )
    assert ledger.sell_taker_fee_pct > ledger.sell_maker_fee_pct > ledger.buy_fee_pct, (
        f"Expected sell_taker > sell_maker > buy, got: "
        f"{ledger.sell_taker_fee_pct} > {ledger.sell_maker_fee_pct} > {ledger.buy_fee_pct}"
    )

    # Verify exact values from config/fees.py
    assert ledger.buy_fee_pct == pytest.approx(IDR_BUY_FEES.maker_pct, abs=1e-6)
    assert ledger.sell_maker_fee_pct == pytest.approx(IDR_SELL_FEES.maker_pct, abs=1e-6)
    assert ledger.sell_taker_fee_pct == pytest.approx(IDR_SELL_FEES.taker_pct, abs=1e-6)


# ─── Test 7: Partial TP uses sell_maker_fee_pct ──────────────────────────────

def test_partial_tp_uses_sell_maker_fee():
    """execute_partial_tp is a patient exit — must use sell_maker_fee_pct."""
    NOTIONAL = 50_000.0
    ENTRY_PRICE = 100_000.0
    PARTIAL_TP_PRICE = 110_000.0

    ledger = _make_ledger()
    res = ledger.place_paper_buy(
        symbol="TESTIDR", price=ENTRY_PRICE, notional_idr=NOTIONAL,
        stop_loss_pct=15.0, take_profit_pct=20.0,
        partial_tp_pct=50.0, partial_tp_price=PARTIAL_TP_PRICE,
    )
    assert res["success"]

    coins_before = ledger.open_positions["TESTIDR"].amount_coins
    partial = ledger.execute_partial_tp("TESTIDR", PARTIAL_TP_PRICE)
    assert partial is not None

    coins_closed = coins_before * 0.50
    gross = coins_closed * PARTIAL_TP_PRICE
    actual_rate = _fee_rate_from_net(gross, partial["net_proceeds_idr"])

    assert abs(actual_rate - IDR_SELL_FEES.maker_pct) < 0.001, (
        f"Partial TP fee wrong: expected {IDR_SELL_FEES.maker_pct:.4f}% (sell_maker), "
        f"got {actual_rate:.4f}%"
    )
