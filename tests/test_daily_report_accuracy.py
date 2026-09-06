#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from Core.Intelligence.council_data_aggregator import CouncilDataAggregator
from Core.Intelligence.daily_report import build_daily_report
from Core.Intelligence.decision_journal import summarize_today
from Core.Intelligence.market_heatmap import _build_from_tickers


def test_ghost_trades_do_not_produce_phantom_unrealized_loss(tmp_path):
    agg = CouncilDataAggregator(MagicMock())
    agg.state_dir = tmp_path
    (tmp_path / "active_trades.json").write_text(
        json.dumps({
            "BTC/IDR": {
                "price": 1001.0,
                "amount": 0.001,
                "cost": 20000.0,
            }
        }),
        encoding="utf-8",
    )
    # Wallet positions has no BTC (empty wallet)
    pnl_info = agg._active_trade_unrealized_pnl([])
    assert pnl_info["unrealized_pnl_idr"] == 0.0
    assert pnl_info["position_cost_basis_idr"] == 0.0
    assert len(pnl_info["positions"]) == 0

    # Wallet has only dust of PEPE, still no BTC
    pnl_info = agg._active_trade_unrealized_pnl([{"coin": "pepe", "amount": 10.0, "value_idr": 1.0}])
    assert pnl_info["unrealized_pnl_idr"] == 0.0
    assert pnl_info["position_cost_basis_idr"] == 0.0


def test_decision_journal_deduplicates_candidates(tmp_path, monkeypatch):
    import Core.Intelligence.decision_journal as dj
    monkeypatch.setattr(dj, "JOURNAL_DIR", tmp_path)
    today_file = tmp_path / f"{dj._now_wib().date().isoformat()}.jsonl"
    
    # Simulate multiple scanner batches emitting the same pair
    events = [
        {"event_type": "SCANNER_CANDIDATES", "top_candidates": [
            {"symbol": "PYR/IDR", "confidence": 0.85, "pump_stage": "CONTINUATION", "change_pct": 30.0},
            {"symbol": "UAI/IDR", "confidence": 0.85, "pump_stage": "CONTINUATION", "change_pct": 25.0},
        ]},
        {"event_type": "SCANNER_CANDIDATES", "top_candidates": [
            {"symbol": "PYR/IDR", "confidence": 0.85, "pump_stage": "CONTINUATION", "change_pct": 36.0},
        ]},
    ]
    with open(today_file, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
            
    summary = dj.summarize_today()
    cands = summary["top_candidates"]
    symbols = [c["symbol"] for c in cands]
    assert symbols == ["PYR/IDR", "UAI/IDR"]
    assert len(cands) == 2


def test_daily_report_candidate_formatting():
    telemetry = {
        "portfolio": {
            "combined_equity_idr": 100000.0,
            "realized_pnl_idr": 0.0,
            "unrealized_pnl_idr": 0.0,
            "active_positions": [],
        }
    }
    with patch("Core.Intelligence.decision_journal.summarize_today") as mock_summary:
        mock_summary.return_value = {
            "top_candidates": [
                {"symbol": "PYR/IDR", "pump_stage": "CONTINUATION", "change_pct": 36.2, "confidence": 0.85},
                {"symbol": "UAI/IDR", "lifecycle": "IGNITION", "trade_grade": "A", "confidence": 0.88},
            ]
        }
        # Detailed full report must show candidates properly formatted
        report = build_daily_report(telemetry, full=True)
        assert "? ?" not in report
        assert "PYR/IDR CONTINUATION +36.2% score 0.85" in report
        assert "UAI/IDR IGNITION grade A score 0.88" in report

        # Concise default report
        concise = build_daily_report(telemetry, full=False)
        assert "🤖 KiBot Daily Report" in concise
        assert "💰 Saldo:" in concise
        assert "🛡️ Status:" in concise
        assert "📊 Trading Hari Ini:" in concise
        assert "🎯 Tindakan Operator:" in concise


def test_daily_report_security_status_circuit_breaker_linkage():
    from Core.Intelligence.daily_report import determine_security_status, determine_operator_action

    # 1. Normal state -> 🟢 AMAN
    gov_normal = {
        "circuit_breaker_tripped": False,
        "overall_drawdown_pct": 0.0,
        "overall_drawdown_threshold_pct": 18.0,
        "allow_new_orders": True,
        "status": "NORMAL",
    }
    badge, status_tag, desc = determine_security_status(gov_normal, services_ok=True)
    action = determine_operator_action(status_tag, gov_normal)
    assert badge == "🟢"
    assert status_tag == "AMAN"
    assert "Tidak ada tindakan yang diperlukan" in action

    # 2. Drawdown warning (e.g. 5.5% drawdown) -> 🟡 WASPADA
    gov_warn = {
        "circuit_breaker_tripped": False,
        "overall_drawdown_pct": 5.5,
        "overall_drawdown_threshold_pct": 18.0,
        "allow_new_orders": True,
        "status": "NORMAL",
    }
    badge, status_tag, desc = determine_security_status(gov_warn, services_ok=True)
    action = determine_operator_action(status_tag, gov_warn)
    assert badge == "🟡"
    assert status_tag == "WASPADA"
    assert "Pantau pergerakan pasar" in action

    # 3. Circuit breaker tripped -> 🔴 TERKUNCI
    gov_tripped = {
        "circuit_breaker_tripped": True,
        "overall_drawdown_pct": 19.2,
        "overall_drawdown_threshold_pct": 18.0,
        "allow_new_orders": False,
        "status": "OVERALL_DRAWDOWN_BREAKER_TRIPPED",
    }
    badge, status_tag, desc = determine_security_status(gov_tripped, services_ok=True)
    action = determine_operator_action(status_tag, gov_tripped)
    assert badge == "🔴"
    assert status_tag == "TERKUNCI"
    assert "Drawdown 19.2% (≥18% limit)" in desc
    assert "drawdown-ack" in action

    # Verify concise report embeds 🔴 TERKUNCI and operator action
    telemetry = {"portfolio": {"combined_equity_idr": 807983.0, "active_positions": []}}
    report = build_daily_report(telemetry=telemetry, full=False)
    # With gov_tripped passed or patched
    from Core.Intelligence.daily_report import build_concise_daily_report
    concise_tripped = build_concise_daily_report(telemetry=telemetry, governor_data=gov_tripped)
    assert "🔴 TERKUNCI" in concise_tripped
    assert "Jalankan 'bin/kibotctl drawdown-ack'" in concise_tripped


def test_daily_report_dynamic_trading_reason():
    from Core.Intelligence.daily_report import determine_trading_reason

    base_gov = {"circuit_breaker_tripped": False, "allow_new_orders": True}
    base_port = {"cash_idr": 500000.0, "active_positions": []}
    order_sum = {}
    trade_sum = {"buy_fills": 0}
    prob = {"estimated_green_probability_pct": 65.0, "confidence_quality": "STRONG"}
    journal = {"top_candidates": [{"symbol": "BTC/IDR", "trade_grade": "A", "opportunity_score": 0.90}]}
    heatmap = {"market_breadth": "BROAD_RISK_ON"}

    # 1. Breaker tripped
    reason = determine_trading_reason(
        {"circuit_breaker_tripped": True}, base_port, order_sum, trade_sum, prob, journal, heatmap, "TERKUNCI"
    )
    assert "Pintu transaksi dikunci total oleh Circuit Breaker" in reason

    # 2. Capital governor lock
    reason = determine_trading_reason(
        {"circuit_breaker_tripped": False, "allow_new_orders": False, "allow_new_orders_reason": "daily loss limit"},
        base_port, order_sum, trade_sum, prob, journal, heatmap, "WASPADA"
    )
    assert "Pintu transaksi dikunci oleh pengaman modal" in reason

    # 3. Already executed buys today
    reason = determine_trading_reason(
        base_gov, base_port, order_sum, {"buy_fills": 2}, prob, journal, heatmap, "AMAN"
    )
    assert "Bot telah mengeksekusi 2 transaksi beli hari ini" in reason

    # 4. Holding real open positions
    port_with_pos = {
        "cash_idr": 500000.0,
        "active_positions": [{"coin": "sol", "amount": 1.0, "value_idr": 2500000.0}],
    }
    reason = determine_trading_reason(
        base_gov, port_with_pos, order_sum, trade_sum, prob, journal, heatmap, "AMAN"
    )
    assert "Bot sedang mengawal 1 posisi aktif (SOL)" in reason

    # 5. Empty / low cash IDR (< 10.000 IDR) and no real positions
    port_no_cash = {"cash_idr": 5000.0, "active_positions": []}
    reason = determine_trading_reason(
        base_gov, port_no_cash, order_sum, trade_sum, prob, journal, heatmap, "AMAN"
    )
    assert "Saldo kas IDR (Rp 5.000) belum mencukupi" in reason

    # 6. Defensive market
    heat_def = {"market_breadth": "DEFENSIVE"}
    reason = determine_trading_reason(
        base_gov, base_port, order_sum, trade_sum, prob, journal, heat_def, "AMAN"
    )
    assert "Kondisi pasar saat ini defensif/berisiko tinggi" in reason

    # 7. Low green probability / no grade A or B
    prob_weak = {"estimated_green_probability_pct": 25.0, "confidence_quality": "WEAK"}
    reason = determine_trading_reason(
        base_gov, base_port, order_sum, trade_sum, prob_weak, {"top_candidates": []}, heatmap, "AMAN"
    )
    assert "Belum ada kandidat koin yang memenuhi standar profit" in reason

    # 8. Normal standby
    reason = determine_trading_reason(
        base_gov, base_port, order_sum, trade_sum, prob, journal, heatmap, "AMAN"
    )
    assert "Bot aktif memantau pasar 24/7 dan hanya masuk saat sinyal profit aman terverifikasi." in reason


def test_market_heatmap_filters_penny_tick_noise():
    tickers = {
        # 1-Rupiah penny coins with minimal volume
        "cht_idr": {"last": "2", "low": "1", "high": "2", "vol_idr": "3661189"},
        "h2o_idr": {"last": "2", "low": "1", "high": "2", "vol_idr": "3789657"},
        # Real liquid pump
        "pyr_idr": {"last": "1107", "low": "813", "high": "1150", "vol_idr": "1475457102"},
        "clv_idr": {"last": "45", "low": "27", "high": "48", "vol_idr": "1265954965"},
        "uai_idr": {"last": "10558", "low": "8410", "high": "11000", "vol_idr": "4084429739"},
    }
    snapshot = _build_from_tickers(tickers)
    top_pairs = [m["pair"] for m in snapshot["top_movers"]]
    # CHT and H2O must not dominate top_movers over real liquid pumps
    assert "CHT/IDR" not in top_pairs[:3]
    assert "H2O/IDR" not in top_pairs[:3]
    assert "CLV/IDR" in top_pairs
    assert "PYR/IDR" in top_pairs
    assert "UAI/IDR" in top_pairs

