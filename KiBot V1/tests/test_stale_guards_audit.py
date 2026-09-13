from __future__ import annotations

from Core.Support.growth_audit import assert_stale_guard_state


def test_stale_guard_state_returns_payload() -> None:
    result = assert_stale_guard_state({"live_truth": {"updated_at": "x"}, "workflow": {"updated_at": "y"}})
    assert "fresh" in result

