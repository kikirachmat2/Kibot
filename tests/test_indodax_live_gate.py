from __future__ import annotations

from pathlib import Path


def test_indodax_live_gate_present_before_trade_call():
    text = Path("Core/Executors/Indodax/indodax_executor.py").read_text(encoding="utf-8")
    assert "evaluate_live_trade(" in text
    trade_idx = text.find('type=side.lower()')
    gate_idx = text.find("evaluate_live_trade(")
    assert trade_idx > 0
    assert gate_idx > 0
    assert gate_idx < trade_idx
