import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from infra.auto_discovery import BatamAutoDiscovery

def _mock_aiohttp_get(status=200, json_data=None):
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data or {"status": "HEALTHY", "node": "BATAM_RESEARCH_NODE", "uptime_s": 10.5})

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_ctx)

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    return mock_session_ctx, mock_session

def test_auto_discovery_online():
    async def _test():
        callback_records = []
        def on_change(online, data):
            callback_records.append((online, data))

        discovery = BatamAutoDiscovery(node_host="localhost", node_port=5001, on_status_change_cb=on_change)
        mock_ctx, _ = _mock_aiohttp_get(status=200)

        with patch("aiohttp.ClientSession", return_value=mock_ctx):
            online = await discovery.check_health()
            assert online is True
            assert discovery.is_online is True
            assert len(callback_records) == 1
            assert callback_records[0][0] is True
            assert callback_records[0][1]["node"] == "BATAM_RESEARCH_NODE"
    asyncio.run(_test())

def test_auto_discovery_offline():
    async def _test():
        callback_records = []
        def on_change(online, data):
            callback_records.append((online, data))

        discovery = BatamAutoDiscovery(node_host="localhost", node_port=5001, on_status_change_cb=on_change)
        discovery.is_online = True  # Was previously online

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(side_effect=Exception("Connection refused"))
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_ctx):
            online = await discovery.check_health()
            assert online is False
            assert discovery.is_online is False
            # Transitioned to offline, callback called
            assert len(callback_records) == 1
            assert callback_records[0][0] is False
    asyncio.run(_test())
