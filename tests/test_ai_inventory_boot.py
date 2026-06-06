from pathlib import Path
import json

from scripts.build_ai_system_inventory import build_inventory


def test_ai_inventory_boot_schema():
    inv = build_inventory()
    assert inv["runtime_mode"] == "LIVE_ONLY"
    assert inv["live_only_policy"]["trading_hot_path"] == "deterministic"
    assert inv["live_only_policy"]["ai_role"] == "advisory_only"
    assert inv["live_only_policy"]["telegram_role"] == "exception_only"
    assert inv["ai_permissions"]["can_place_order"] is False
    assert inv["ai_permissions"]["can_override_gate"] is False
    assert inv["summary"]["total_components"] >= 20
    assert inv["summary"]["active_components"] >= 15
    assert inv["summary"]["locked_or_conditional_components"] >= 0


def test_ai_inventory_component_permissions_are_denied():
    inv = build_inventory()
    for group in inv["categories"].values():
        for component in group:
            assert component["can_place_order"] is False
            assert component["can_override_gate"] is False
