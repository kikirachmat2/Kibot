from __future__ import annotations

from Core.Support.no_trade_forensics import build_no_trade_forensics


def test_forensics_has_movement_fields() -> None:
    payload = build_no_trade_forensics()
    assert "movement_status" in payload
    assert "movement_reason" in payload
    assert "micro_probe" in payload
    assert "trade_tiers_24h" in payload

