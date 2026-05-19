import json

import pytest

from Core.Web3.web3_exit_daemon import Web3ExitDaemon


@pytest.mark.anyio
async def test_exit_daemon_keeps_open_when_quote_missing(monkeypatch, tmp_path):
    positions_file = tmp_path / "web3_positions.json"
    positions_file.write_text(json.dumps([{
        "id": "p1",
        "network": "solana",
        "asset": "USRX",
        "amount_raw": 1000,
        "entry_value_idr": 5000,
        "status": "OPEN",
    }]))

    monkeypatch.setattr("Core.Web3.web3_exit_daemon.STATE_DIR", tmp_path)
    monkeypatch.setattr("Core.Web3.web3_exit_daemon.POSITIONS_FILE", positions_file)
    monkeypatch.setattr("Core.Web3.web3_exit_daemon.EXIT_STATE_FILE", tmp_path / "web3_exit_state.json")

    async def fake_quote(self, route, input_asset, output_asset, amount_raw):
        return {"quote_ok": False, "reason": "quote_context_missing", "expected_out": 0, "expires_at": None}

    monkeypatch.setattr("Core.Web3.web3_exit_daemon.Web3QuoteRouter.quote", fake_quote)
    daemon = Web3ExitDaemon()
    state = await daemon.tick_async()
    saved = json.loads(positions_file.read_text())
    assert saved[0]["status"] == "EXIT_RECOMMENDED"
    assert saved[0]["needs_operator_attention"] is True
    assert state["positions_recommended"] == 1
