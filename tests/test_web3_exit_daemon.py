import json
from pathlib import Path

from Core.Web3.web3_exit_daemon import Web3ExitDaemon


def test_web3_exit_daemon_closes_stale_position(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    positions_file = state_dir / "web3_positions.json"
    positions_file.write_text(json.dumps([{
        "id": "pos-1",
        "network": "solana",
        "asset": "TEST",
        "entry_value_idr": 1000,
        "amount": 1.0,
        "opened_at_ts": 0,
        "stop_loss_pct": 1.5,
        "take_profit_pct": 1.0,
        "trailing_stop_pct": 0.5,
        "time_stop_seconds": 1,
        "status": "OPEN",
    }]))
    monkeypatch.setattr("Core.Web3.web3_exit_daemon.STATE_DIR", state_dir)
    monkeypatch.setattr("Core.Web3.web3_exit_daemon.POSITIONS_FILE", positions_file)
    monkeypatch.setattr("Core.Web3.web3_exit_daemon.EXIT_STATE_FILE", state_dir / "web3_exit_state.json")

    daemon = Web3ExitDaemon()
    daemon._refresh_quote = lambda position: {"quote_ok": False, "expected_out": 0, "reason": "stale"}  # type: ignore[attr-defined]
    state = daemon.tick()

    assert state["positions_closed"] == 1
    saved = json.loads(positions_file.read_text())
    assert saved[0]["status"] == "CLOSED"

