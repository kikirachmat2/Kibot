#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "ai_system_inventory.json"


def main() -> int:
    if not STATE.exists():
        print("FAIL:ai_system_inventory_missing")
        return 1
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"FAIL:ai_system_inventory_invalid:{exc}")
        return 1

    summary = data.get("summary", {}) if isinstance(data, dict) else {}
    policy = data.get("live_only_policy", {}) if isinstance(data, dict) else {}
    permissions = data.get("ai_permissions", {}) if isinstance(data, dict) else {}

    if str(data.get("runtime_mode") or "") != "LIVE_ONLY":
        print(f"FAIL:runtime_mode={data.get('runtime_mode')}")
        return 1
    if int(summary.get("total_components", 0) or 0) < 20:
        print("FAIL:total_components_too_low")
        return 1
    if int(summary.get("active_components", 0) or 0) < 15:
        print("FAIL:active_components_too_low")
        return 1
    if policy.get("trading_hot_path") != "deterministic":
        print("FAIL:trading_hot_path_not_deterministic")
        return 1
    if policy.get("ai_role") != "advisory_only":
        print("FAIL:ai_role_not_advisory_only")
        return 1
    if policy.get("telegram_role") != "exception_only":
        print("FAIL:telegram_role_not_exception_only")
        return 1
    if permissions.get("can_place_order") is not False:
        print("FAIL:ai_can_place_order")
        return 1
    if permissions.get("can_override_gate") is not False:
        print("FAIL:ai_can_override_gate")
        return 1

    components = []
    for group in data.get("categories", {}).values():
        if isinstance(group, list):
            components.extend(group)
    if any(c.get("can_place_order") for c in components if isinstance(c, dict)):
        print("FAIL:component_can_place_order_true")
        return 1
    if any(c.get("can_override_gate") for c in components if isinstance(c, dict)):
        print("FAIL:component_can_override_gate_true")
        return 1

    print("OK:AI_INVENTORY_BOOT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
