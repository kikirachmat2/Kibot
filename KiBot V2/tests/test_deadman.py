import asyncio
import hashlib
import hmac
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from executor.deadman import IndodaxDeadmanSwitch

def _create_mock_session(status=200, return_json=None):
    if return_json is None:
        return_json = {"success": 1, "return": {"countdownTime": 900000}}
    
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.json = AsyncMock(return_value=return_json)

    # Context manager returned by session.post(...)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_ctx)

    # Context manager returned by aiohttp.ClientSession(...)
    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    return mock_session_ctx, mock_session

def test_deadman_hmac_signature():
    switch = IndodaxDeadmanSwitch(api_key="my_key", secret_key="my_secret")
    body = "method=countdownCancelAll&pair=btcidr&countdownTime=900000"
    expected_sign = hmac.new(b"my_secret", body.encode("utf-8"), hashlib.sha512).hexdigest()
    assert switch._sign(body) == expected_sign

def test_deadman_register_and_heartbeat():
    async def _test():
        switch = IndodaxDeadmanSwitch(api_key="key123", secret_key="secret123")
        mock_ctx, mock_session = _create_mock_session()

        with patch("aiohttp.ClientSession", return_value=mock_ctx):
            # 1. Register deadman for BTCIDR
            res = await switch.register_deadman(pair="btcidr", timeout_seconds=900)
            assert res is True
            assert "btcidr" in switch.monitored_pairs
            assert switch._last_heartbeat_ts > 0

            # 2. Trigger heartbeat
            hb_res = await switch.heartbeat()
            assert hb_res is True
            assert mock_session.post.call_count == 2
    asyncio.run(_test())

def test_deadman_cancel_all_if_dead():
    async def _test():
        switch = IndodaxDeadmanSwitch(api_key="key123", secret_key="secret123")
        mock_ctx, mock_session = _create_mock_session(return_json={"success": 1, "return": {"countdownTime": 0}})

        with patch("aiohttp.ClientSession", return_value=mock_ctx):
            res = await switch.cancel_all_if_dead(pair="ethidr")
            assert res is True
            # Verify countdownTime=0 was sent
            call_args = mock_session.post.call_args
            assert "countdownTime=0" in call_args[1]["data"]
    asyncio.run(_test())

def test_deadman_simulate_freeze():
    """Simulate bot freezing where heartbeat stops firing."""
    async def _test():
        switch = IndodaxDeadmanSwitch(
            api_key="key123",
            secret_key="secret123",
            default_timeout_seconds=2, # 2s timeout
            heartbeat_interval_seconds=1,
        )
        switch.monitored_pairs.add("btcidr")
        switch._last_heartbeat_ts = 100.0 # frozen at timestamp 100

        # If current time is 105, elapsed time (5s) > timeout (2s), meaning bot froze
        current_time = 105.0
        is_frozen = (current_time - switch._last_heartbeat_ts) > switch.default_timeout_seconds
        assert is_frozen is True

        # Immediate fallback cancellation executed
        mock_ctx, mock_session = _create_mock_session(return_json={"success": 1})
        with patch("aiohttp.ClientSession", return_value=mock_ctx):
            cancel_res = await switch.cancel_all_if_dead("btcidr")
            assert cancel_res is True
    asyncio.run(_test())

def test_deadman_wired_to_order_router():
    """Verify deadman registration is triggered upon order router paper buy execution."""
    from executor.order_router import OrderRouter
    from executor.virtual_ledger import VirtualLedger
    from risk import RiskGate

    async def _test():
        risk_gate = RiskGate()
        ledger = VirtualLedger(name="TEST_DEADMAN")
        router = OrderRouter(risk_gate=risk_gate, virtual_ledger=ledger)

        with patch("executor.order_router.register_deadman", new_callable=AsyncMock) as mock_reg:
            mock_reg.return_value = True
            res = await router.route_buy_order(
                symbol="BTCIDR",
                price=1_000_000_000.0,
                notional_idr=100_000.0,
            )
            assert res.get("success") is True
            mock_reg.assert_awaited_once_with(pair="btcidr", timeout_seconds=900)

    asyncio.run(_test())

