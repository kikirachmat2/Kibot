from __future__ import annotations

from Core.Support.round_trip_accounting import build_round_trip_accounting


def test_round_trip_accounting_builds_closed_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("Core.Support.round_trip_accounting.STATE_DIR", tmp_path)
    result = build_round_trip_accounting(
        {
            "trade_history": [
                {"venue": "indodax", "pair": "EDEN/IDR", "side": "BUY", "status": "FILLED", "amount_idr": 10000, "amount_coin": 100, "timestamp_wib": "2026-06-02T00:00:00+00:00"},
                {"venue": "indodax", "pair": "EDEN/IDR", "side": "SELL", "status": "FILLED", "amount_idr": 11000, "amount_coin": 100, "net_realized_pnl_idr": 900, "fee_idr": 100, "timestamp_wib": "2026-06-02T00:10:00+00:00"},
            ]
        }
    )
    assert result["stats"]["closed_round_trips"] == 1

