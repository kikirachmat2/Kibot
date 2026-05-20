import asyncio
import json

import pytest

from Core.Web3.web3_exit_daemon import Web3ExitDaemon


@pytest.mark.anyio
async def test_refresh_quote_awaits_router_quote(monkeypatch):
    daemon = Web3ExitDaemon()
    called = {}

    class DummyRouter:
        async def quote(self, *, route, input_asset, output_asset, amount_raw, **kwargs):
            called["route"] = route
            called["input_asset"] = input_asset
            called["output_asset"] = output_asset
            called["amount_raw"] = amount_raw
            return {"quote_ok": True, "expected_out": 1234, "expires_at": "soon"}

    monkeypatch.setattr("Core.Web3.web3_exit_daemon.Web3QuoteRouter", DummyRouter)
    quote = await daemon._refresh_quote({
        "network": "solana",
        "input_asset": "So11111111111111111111111111111111111111112",
        "output_asset": "USDC",
        "amount_raw": 100,
    })

    assert called["amount_raw"] == 100
    assert called["route"] == "solana"
    assert quote["quote_ok"] is True


@pytest.mark.anyio
async def test_missing_amount_raw_returns_context_missing(monkeypatch):
    daemon = Web3ExitDaemon()
    quote = await daemon._refresh_quote({"network": "solana", "asset": "TEST"})
    assert quote["quote_ok"] is False
    assert quote["reason"] == "quote_context_missing"


@pytest.mark.anyio
async def test_stale_quote_marks_recommendation_not_closed(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    positions_file = state_dir / "web3_positions.json"
    positions_file.write_text(json.dumps([{
        "id": "pos-1",
        "network": "solana",
        "asset": "TEST",
        "input_asset": "TEST",
        "output_asset": "USDC",
        "amount_raw": 100,
        "entry_value_idr": 1000,
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
    daemon._refresh_quote = lambda position: asyncio.sleep(0, result={"quote_ok": False, "reason": "stale_quote", "expected_out": 0})  # type: ignore[assignment]
    state = await daemon.tick_async()
    saved = json.loads(positions_file.read_text())
    assert saved[0]["status"] == "EXIT_RECOMMENDED"
    assert saved[0]["exit_reason"] == "stale_quote"
    assert state["positions_recommended"] == 1


@pytest.mark.anyio
async def test_take_profit_creates_recommendation_first(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    positions_file = state_dir / "web3_positions.json"
    positions_file.write_text(json.dumps([{
        "id": "pos-2",
        "network": "solana",
        "asset": "TEST",
        "input_asset": "TEST",
        "output_asset": "USDC",
        "amount_raw": 100,
        "entry_value_idr": 1000,
        "opened_at_ts": 0,
        "stop_loss_pct": 1.5,
        "take_profit_pct": 1.0,
        "trailing_stop_pct": 0.5,
        "time_stop_seconds": 999999,
        "status": "OPEN",
    }]))
    monkeypatch.setattr("Core.Web3.web3_exit_daemon.STATE_DIR", state_dir)
    monkeypatch.setattr("Core.Web3.web3_exit_daemon.POSITIONS_FILE", positions_file)
    monkeypatch.setattr("Core.Web3.web3_exit_daemon.EXIT_STATE_FILE", state_dir / "web3_exit_state.json")
    daemon = Web3ExitDaemon()
    daemon._refresh_quote = lambda position: asyncio.sleep(0, result={"quote_ok": True, "reason": "", "expected_out": 1105, "expires_at": "soon"})  # type: ignore[assignment]
    await daemon.tick_async()
    saved = json.loads(positions_file.read_text())
    assert saved[0]["status"] == "EXIT_RECOMMENDED"
    assert saved[0]["exit_reason"] == "take_profit"


@pytest.mark.anyio
async def test_stop_loss_creates_recommendation_first(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    positions_file = state_dir / "web3_positions.json"
    positions_file.write_text(json.dumps([{
        "id": "pos-3",
        "network": "solana",
        "asset": "TEST",
        "input_asset": "TEST",
        "output_asset": "USDC",
        "amount_raw": 100,
        "entry_value_idr": 1000,
        "opened_at_ts": 0,
        "stop_loss_pct": 1.5,
        "take_profit_pct": 9.0,
        "trailing_stop_pct": 0.5,
        "time_stop_seconds": 999999,
        "status": "OPEN",
    }]))
    monkeypatch.setattr("Core.Web3.web3_exit_daemon.STATE_DIR", state_dir)
    monkeypatch.setattr("Core.Web3.web3_exit_daemon.POSITIONS_FILE", positions_file)
    monkeypatch.setattr("Core.Web3.web3_exit_daemon.EXIT_STATE_FILE", state_dir / "web3_exit_state.json")
    daemon = Web3ExitDaemon()
    daemon._refresh_quote = lambda position: asyncio.sleep(0, result={"quote_ok": True, "reason": "", "expected_out": 970, "expires_at": "soon"})  # type: ignore[assignment]
    await daemon.tick_async()
    saved = json.loads(positions_file.read_text())
    assert saved[0]["status"] == "EXIT_RECOMMENDED"
    assert saved[0]["exit_reason"] == "stop_loss"
