import json
from pathlib import Path


def test_dashboard_independent_states_exist():
    state_dir = Path("state")
    assert (state_dir / "engine_independence.json").exists()
    assert (state_dir / "indodax_no_idle.json").exists()
    assert (state_dir / "phantom_retirement.json").exists()
    assert (state_dir / "deadline_profit_enforcer.json").exists()
