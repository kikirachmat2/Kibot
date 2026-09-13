from pathlib import Path


def test_indodax_executor_uses_deterministic_gate_before_trade():
    text = Path("Core/Executors/Indodax/indodax_executor.py").read_text(encoding="utf-8")
    gate_pos = text.find("evaluate_live_trade(")
    trade_pos = text.find('type=side.lower()')
    assert gate_pos >= 0
    assert trade_pos >= 0
    assert gate_pos < trade_pos
    assert "from Core.Decision.deterministic_decision_gate import evaluate_live_trade" in text


def test_live_truth_has_indodax_block():
    text = Path("state/live_truth.json").read_text(encoding="utf-8") if Path("state/live_truth.json").exists() else "{}"
    assert '"indodax"' in text
