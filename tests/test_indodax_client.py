"""
Unit tests for IndodaxClient wrapper including error handling and order execution.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from ingestion.indodax_client import IndodaxClient


def test_signature_generation():
    client = IndodaxClient(api_key="test_key", api_secret="test_secret")
    params = {"timestamp": 1234567890, "recvWindow": 5000}
    sig = client._sign_payload_v2(params)
    assert isinstance(sig, str)
    assert len(sig) == 64  # SHA-256 hex length


def test_get_ticker_mock():
    async def _run():
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={
            "ticker": {
                "high": "1430000000",
                "low": "1410000000",
                "buy": "1423000000",
                "sell": "1424000000",
                "last": "1423500000"
            }
        })
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        mock_ctx.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        mock_session.get.return_value = mock_ctx

        with patch("aiohttp.ClientSession", return_value=mock_session):
            client = IndodaxClient()
            client._session = mock_session
            ticker = await client.get_ticker("btc_idr")
            assert ticker["buy"] == "1423000000"
            assert ticker["sell"] == "1424000000"
            await client.close()

    asyncio.run(_run())


def test_get_balance_mock():
    async def _run():
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={
            "canTrade": True,
            "canWithdraw": False,
            "balances": [
                {"asset": "IDR", "free": "500000", "locked": "0"},
                {"asset": "BTC", "free": "0.005", "locked": "0"},
                {"asset": "USDT", "free": "10.5", "locked": "0"}
            ]
        })
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        mock_ctx.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        mock_session.get.return_value = mock_ctx

        with patch("aiohttp.ClientSession", return_value=mock_session):
            client = IndodaxClient(api_key="key", api_secret="secret")
            client._session = mock_session
            balances = await client.get_balance()
            assert balances["idr"] == 500000.0
            assert balances["btc"] == 0.005
            assert balances["usdt"] == 10.5
            await client.close()

    asyncio.run(_run())


def test_get_balance_errors_and_missing_creds():
    async def _run():
        client = IndodaxClient()
        with pytest.raises(ValueError, match="API credentials missing"):
            await client.get_balance()

        # Test API failure response
        mock_resp = AsyncMock()
        mock_resp.status = 403
        mock_resp.text = AsyncMock(return_value="Access denied for this API key version.")
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        mock_ctx.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.get.return_value = mock_ctx

        client_auth = IndodaxClient(api_key="k", api_secret="s")
        client_auth._session = mock_session
        with pytest.raises(RuntimeError, match="Indodax API error"):
            await client_auth.get_balance()

    asyncio.run(_run())


def test_place_buy_order():
    async def _run():
        client_no_auth = IndodaxClient()
        with pytest.raises(ValueError, match="API credentials missing"):
            await client_no_auth.place_buy_order("btc_idr", 1_400_000_000, 0.001)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={
            "orderId": "123456",
            "symbol": "btcidr",
            "status": "NEW"
        })
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        mock_ctx.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.post.return_value = mock_ctx

        client = IndodaxClient(api_key="k", api_secret="s")
        client._session = mock_session
        res = await client.place_buy_order("btc_idr", 1_400_000_000, 0.001, order_type="LIMIT")
        assert res["orderId"] == "123456"

        # Test order failure
        mock_resp_fail = AsyncMock()
        mock_resp_fail.status = 400
        mock_resp_fail.text = AsyncMock(return_value="Insufficient balance")
        mock_ctx_fail = AsyncMock()
        mock_ctx_fail.__aenter__.return_value = mock_resp_fail
        mock_ctx_fail.__aexit__.return_value = None
        mock_session.post.return_value = mock_ctx_fail

        with pytest.raises(RuntimeError, match="Buy order placement failed"):
            await client.place_buy_order("btc_idr", 1_400_000_000, 0.001)

    asyncio.run(_run())
