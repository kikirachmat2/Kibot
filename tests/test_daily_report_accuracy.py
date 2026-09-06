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
        report = build_daily_report(telemetry)
        assert "? ?" not in report
        assert "PYR/IDR CONTINUATION +36.2% score 0.85" in report
        assert "UAI/IDR IGNITION grade A score 0.88" in report


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
