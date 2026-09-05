from pathlib import Path

from scripts.archive.asserts import assert_server_truth_runtime as truth


def test_required_state_list_present():
    assert "engine_independence.json" in truth.REQUIRED
    assert "server_telemetry.json" in truth.REQUIRED
