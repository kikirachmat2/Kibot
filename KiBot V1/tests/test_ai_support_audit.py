from __future__ import annotations

from Core.Support.money_movement_audit import ai_support_audit


def test_ai_support_audit_has_expected_keys() -> None:
    result = ai_support_audit({"ai_system_inventory": {"categories": {}}, "ai_patrol": {"support_action": "continue"}})
    assert "ai_health" in result
    assert "can_place_order" in result
    assert "can_override_gate" in result

