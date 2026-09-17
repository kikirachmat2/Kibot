"""
Unit tests for KiBot V2 Backtest Friction Model.
Tests run completely offline without external network or API access.
"""
import pytest
from backtest.friction import (
    OrderType,
    StrategyType,
    PAIR_FRICTION,
    get_roundtrip_friction,
    get_adverse_penalty,
    should_fill,
    compute_pnl_after_costs,
)


def test_maker_friction_less_than_taker_for_all_pairs():
    """Verifies that maker friction is strictly lower than taker friction for all pairs."""
    for pair in PAIR_FRICTION:
        maker_friction = get_roundtrip_friction(pair, OrderType.MAKER)
        taker_friction = get_roundtrip_friction(pair, OrderType.TAKER)
        assert maker_friction < taker_friction, f"Maker ({maker_friction}) should be < Taker ({taker_friction}) for {pair}"
        assert maker_friction > 0, f"Maker friction must be > 0 for {pair}"
        assert taker_friction > 0, f"Taker friction must be > 0 for {pair}"

    # Specific baseline values from STRATEGY_EVALUATION_REVISED.md
    assert get_roundtrip_friction("BTCIDR", OrderType.MAKER) == 0.56
    assert get_roundtrip_friction("BTCIDR", OrderType.TAKER) == 0.78
    assert get_roundtrip_friction("ETHIDR", OrderType.MAKER) == 0.56
    assert get_roundtrip_friction("ETHIDR", OrderType.TAKER) == 0.78
    assert get_roundtrip_friction("SOLIDR", OrderType.MAKER) == 0.70
    assert get_roundtrip_friction("SOLIDR", OrderType.TAKER) == 0.95
    assert get_roundtrip_friction("AVAXIDR", OrderType.MAKER) == 0.70
    assert get_roundtrip_friction("AVAXIDR", OrderType.TAKER) == 0.95


def test_adverse_penalty_values():
    """Verifies adverse selection penalty: MR = 0.30 (30%), LL = 0.40 (40%)."""
    assert get_adverse_penalty(StrategyType.MEAN_REVERSION) == 0.30
    assert get_adverse_penalty(StrategyType.LEAD_LAG) == 0.40


def test_should_fill_deterministic_and_reproducible():
    """Verifies should_fill produces reproducible results with random seeds."""
    normal_bar = {
        "open": 100_000_000,
        "high": 102_000_000,
        "low": 99_000_000,
        "close": 101_000_000,
        "volume": 5.0,
    }
    quiet_bar = {
        "open": 100_000_000,
        "high": 100_050_000,  # 0.05% range (< 0.1%)
        "low": 100_000_000,
        "close": 100_020_000,
        "volume": 0.1,
    }

    # Taker is always 100% fill (fill_rate = 1.0)
    for _ in range(20):
        assert should_fill(OrderType.TAKER, normal_bar) is True
        assert should_fill(OrderType.TAKER, quiet_bar) is True

    # Determinism with seed
    seed = 42
    run1 = [should_fill(OrderType.MAKER, normal_bar, random_seed=seed + i) for i in range(100)]
    run2 = [should_fill(OrderType.MAKER, normal_bar, random_seed=seed + i) for i in range(100)]
    assert run1 == run2, "Execution with identical seeds must be strictly reproducible"

    # Fill rate empirical validation across large sample
    n_samples = 10_000
    fills_normal = sum(should_fill(OrderType.MAKER, normal_bar, random_seed=10000 + i) for i in range(n_samples))
    rate_normal = fills_normal / n_samples
    assert 0.83 < rate_normal < 0.87, f"Normal fill rate should be ~0.85, got {rate_normal}"

    fills_quiet = sum(should_fill(OrderType.MAKER, quiet_bar, random_seed=20000 + i) for i in range(n_samples))
    rate_quiet = fills_quiet / n_samples
    assert 0.68 < rate_quiet < 0.72, f"Quiet bar fill rate should be ~0.70, got {rate_quiet}"


def test_compute_pnl_after_costs_btc_maker_example():
    """
    Test compute_pnl_after_costs with exact BTC trade:
    - Position size: Rp 500.000.000 (500jt IDR)
    - Entry: 1.000.000.000 IDR
    - Exit: +1.0% (1.010.000.000 IDR)
    - Pair: BTCIDR
    - Order type: MAKER (0.56% friction)
    """
    entry_price = 1_000_000_000.0
    exit_price = 1_010_000_000.0  # +1.0%
    position_size_idr = 500_000_000.0

    # Mean Reversion: 30% adverse penalty
    res_mr = compute_pnl_after_costs(
        entry_price=entry_price,
        exit_price=exit_price,
        position_size_idr=position_size_idr,
        pair="BTCIDR",
        order_type=OrderType.MAKER,
        strategy=StrategyType.MEAN_REVERSION,
    )

    # Verification of exact values:
    # gross_pnl = 500M * 0.01 = 5.000.000 IDR
    # friction = 500M * 0.0056 = 2.800.000 IDR
    # adverse_penalty = 5.000.000 * 0.30 = 1.500.000 IDR
    # net_pnl = 5.000.000 - 2.800.000 - 1.500.000 = 700.000 IDR
    # net_pnl_pct = (700.000 / 500.000.000) * 100 = 0.14%
    assert res_mr["gross_pnl_idr"] == 5_000_000.0
    assert res_mr["friction_idr"] == 2_800_000.0
    assert res_mr["adverse_penalty_idr"] == 1_500_000.0
    assert res_mr["net_pnl_idr"] == 700_000.0
    assert res_mr["net_pnl_pct"] == 0.14

    # Lead Lag: 40% adverse penalty
    res_ll = compute_pnl_after_costs(
        entry_price=entry_price,
        exit_price=exit_price,
        position_size_idr=position_size_idr,
        pair="BTCIDR",
        order_type=OrderType.MAKER,
        strategy=StrategyType.LEAD_LAG,
    )
    # adverse_penalty = 5.000.000 * 0.40 = 2.000.000 IDR
    # net_pnl = 5.000.000 - 2.800.000 - 2.000.000 = 200.000 IDR
    # net_pnl_pct = (200.000 / 500.000.000) * 100 = 0.04%
    assert res_ll["gross_pnl_idr"] == 5_000_000.0
    assert res_ll["friction_idr"] == 2_800_000.0
    assert res_ll["adverse_penalty_idr"] == 2_000_000.0
    assert res_ll["net_pnl_idr"] == 200_000.0
    assert res_ll["net_pnl_pct"] == 0.04


def test_edge_case_loss_trade_strictly_net_negative():
    """Verifies edge case where exit_price < entry_price (loss) is strictly net negative."""
    entry_price = 1_000_000_000.0
    exit_price = 990_000_000.0  # -1.0% loss
    position_size_idr = 500_000_000.0

    res = compute_pnl_after_costs(
        entry_price=entry_price,
        exit_price=exit_price,
        position_size_idr=position_size_idr,
        pair="BTCIDR",
        order_type=OrderType.MAKER,
        strategy=StrategyType.MEAN_REVERSION,
    )

    # Gross PnL: -5.000.000 IDR
    # Friction: 2.800.000 IDR
    # Adverse penalty on loss: 0.0 IDR (no positive edge to discount)
    # Net PnL: -5.000.000 - 2.800.000 = -7.800.000 IDR
    assert res["gross_pnl_idr"] == -5_000_000.0
    assert res["friction_idr"] == 2_800_000.0
    assert res["adverse_penalty_idr"] == 0.0
    assert res["net_pnl_idr"] == -7_800_000.0
    assert res["net_pnl_pct"] == -1.56
    assert res["net_pnl_idr"] < res["gross_pnl_idr"] < 0, "Net loss must be strictly worse than gross loss due to friction"
