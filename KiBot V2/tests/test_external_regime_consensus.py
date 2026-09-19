import asyncio
import time
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from council.regime_detector import MarketRegime
from council.external_regime_consensus import ExternalRegimeConsensus

def _mock_aiohttp_get(status=200, json_data=None):
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data or {"regime": "chop", "confidence": 1.0})

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_ctx)

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    return mock_session_ctx, mock_session

def test_consensus_full_agreement():
    consensus = ExternalRegimeConsensus()
    ext_info = {"normalized_regime": MarketRegime.BULL, "confidence": 0.9}
    res = consensus.compute_consensus(
        internal_regime=MarketRegime.BULL,
        internal_strength=80.0,
        external_info=ext_info
    )
    assert res["consensus_status"] == "AGREED"
    assert res["adjusted_strength"] == 80.0
    assert res["damping_multiplier"] == 1.0

def test_consensus_partial_disagreement():
    consensus = ExternalRegimeConsensus()
    # Internal is BULL (+1), External is RANGE (0) -> distance = 1
    ext_info = {"normalized_regime": MarketRegime.RANGE, "confidence": 0.75}
    res = consensus.compute_consensus(
        internal_regime=MarketRegime.BULL,
        internal_strength=80.0,
        external_info=ext_info
    )
    assert res["consensus_status"] == "PARTIAL_DISAGREEMENT"
    assert res["damping_multiplier"] == 0.85
    assert res["adjusted_strength"] == 68.0

def test_consensus_full_disagreement():
    consensus = ExternalRegimeConsensus()
    # Internal is BULL (+1), External is BEAR (-1) -> distance = 2
    ext_info = {"normalized_regime": MarketRegime.BEAR, "confidence": 0.85}
    res = consensus.compute_consensus(
        internal_regime=MarketRegime.BULL,
        internal_strength=80.0,
        external_info=ext_info
    )
    assert res["consensus_status"] == "FULL_DISAGREEMENT"
    assert res["damping_multiplier"] == 0.50
    assert res["adjusted_strength"] == 40.0

def test_consensus_api_down_fallback_100_pct():
    consensus = ExternalRegimeConsensus()
    res = consensus.compute_consensus(
        internal_regime=MarketRegime.BULL,
        internal_strength=80.0,
        external_info=None
    )
    assert res["consensus_status"] == "FALLBACK_INTERNAL"
    assert res["adjusted_strength"] == 80.0
    assert res["damping_multiplier"] == 1.0
    assert res["external_regime"] is None

def test_fetch_external_regime_and_caching():
    async def _test():
        consensus = ExternalRegimeConsensus(cache_ttl=300)
        mock_ctx, mock_session = _mock_aiohttp_get(json_data={"regime": "bull_market", "confidence": 0.95})

        with patch("aiohttp.ClientSession", return_value=mock_ctx):
            # 1. First fetch triggers network call
            data1 = await consensus.fetch_external_regime()
            assert data1 is not None
            assert data1["normalized_regime"] == MarketRegime.BULL
            assert mock_session.get.call_count == 1

            # 2. Second immediate fetch hits cache (no new network call)
            data2 = await consensus.fetch_external_regime()
            assert data2 == data1
            assert mock_session.get.call_count == 1
    asyncio.run(_test())
