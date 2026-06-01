from __future__ import annotations

from Core.Support.growth_audit import audit_phantom_non_movement


def test_phantom_non_movement_classifies_no_edge_when_no_targets() -> None:
    result = audit_phantom_non_movement({"phantom_targets": {"top_targets": []}, "candidate_decisions": []})
    assert result["classification"] in {"PHANTOM_NO_EDGE", "PHANTOM_READY_BUT_WAITING", "PHANTOM_EXECUTOR_NOT_RECEIVING"}

