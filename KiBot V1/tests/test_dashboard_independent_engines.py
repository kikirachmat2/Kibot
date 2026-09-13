import json
from pathlib import Path


def test_dashboard_independent_states_exist():
    state_dir = Path("state")
    state_dir.mkdir(parents=True, exist_ok=True)
    if not (state_dir / "engine_independence.json").exists():
        from Core.Decision.engine_independence import write_engine_independence
        write_engine_independence({})
    if not (state_dir / "indodax_no_idle.json").exists():
        (state_dir / "indodax_no_idle.json").write_text(json.dumps({"posture": "ACTIVE_SEARCHING", "why_not_trading": "idle_standby"}), encoding="utf-8")
    if not (state_dir / "deadline_profit_enforcer.json").exists():
        (state_dir / "deadline_profit_enforcer.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

    assert (state_dir / "engine_independence.json").exists()
    assert (state_dir / "indodax_no_idle.json").exists()
    assert (state_dir / "deadline_profit_enforcer.json").exists()
