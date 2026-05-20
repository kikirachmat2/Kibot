import pytest

from Core.Web3.web3_fee_intelligence import build_fee_intelligence


def test_solana_fee_intelligence_blocks_tiny_trade_without_native_sol(monkeypatch):
    monkeypatch.setenv("SOL_USD_RATE", "170")
    monkeypatch.setenv("USD_IDR_RATE", "16000")
    payload = build_fee_intelligence(
        "solana",
        trade_size_idr=50.0,
        balance_snapshot={"sol_balance": 0.0},
        route_context={"source": "test"},
    )
    assert payload["route_family"] == "solana"
    assert payload["gas_affordable"] is False
    assert payload["gas_reason"] in {"gasless_surcharge_exceeds_10pct_cap", "solana_gas_balance_below_reserve"}
    assert payload["gas_fee_idr"] >= 0


def test_base_fee_intelligence_marks_small_trade_fee_floor(monkeypatch):
    monkeypatch.setenv("BASE_GAS_IDR_ESTIMATE", "15000")
    monkeypatch.setenv("BASE_L2_EXECUTION_GAS_IDR_ESTIMATE", "6000")
    monkeypatch.setenv("BASE_L1_SECURITY_GAS_IDR_ESTIMATE", "9000")
    payload = build_fee_intelligence(
        "base_swap",
        trade_size_idr=10000.0,
        balance_snapshot={"base_gas_balance_idr": 5000},
        route_context={"source": "test"},
    )
    assert payload["route_family"] == "base"
    assert payload["gas_fee_idr"] >= 15000
    assert payload["gas_affordable"] is False
    assert payload["gas_reason"] in {"base_gas_balance_below_fee_floor", "base_l1_fee_dominates_small_trade"}
