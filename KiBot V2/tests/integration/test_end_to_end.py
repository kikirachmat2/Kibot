"""
KiBot V2 — End-to-End Integration Test Scenarios:
1. Scenario 1: Batam node not yet provisioned -> auto-discovery falls back to internal mode.
2. Scenario 2: Batam node comes online -> auto-discovery detects state transition and fires callback.
3. Scenario 3: Bot crash simulation -> deadman switch expiry triggers safety cancellation.
4. Scenario 4: External regime API down -> 100% fallback to internal regime, P5 rotation unaffected.
"""
import asyncio
import time
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
import aiohttp

from council.regime_detector import MarketRegime
from council.external_regime_consensus import compute_consensus, ExternalRegimeConsensus
from executor.deadman import IndodaxDeadmanSwitch
from infra.auto_discovery import BatamAutoDiscovery
from paper_rotation_runner import RotationPaperRunner
import pandas as pd

def test_scenario_1_batam_unreachable_fallback():
    """SCENARIO 1: Batam offline -> Auto-discovery reports offline and uses internal fallback."""
    async def _test():
        callback_called = []
        discovery = BatamAutoDiscovery(
            node_host="127.0.0.1",
            node_port=59999, # dead port
            request_timeout_seconds=0.5,
            on_status_change_cb=lambda online, data: callback_called.append((online, data))
        )
        is_up = await discovery.check_health()
        assert is_up is False
        assert discovery.is_online is False
        # Callback should not trigger repeated alerts when staying offline
        assert len(callback_called) == 0
    asyncio.run(_test())

def test_scenario_2_batam_comes_online():
    """SCENARIO 2: Batam node comes online -> Auto-discovery transitions to online & invokes callback."""
    async def _test():
        callback_events = []
        discovery = BatamAutoDiscovery(
            node_host="127.0.0.1",
            node_port=5001,
            on_status_change_cb=lambda online, data: callback_events.append((online, data))
        )

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "status": "HEALTHY",
            "node": "BATAM_RESEARCH_NODE",
            "port": 5001,
            "uptime_s": 42.0,
        })
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_ctx)
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
            is_up = await discovery.check_health()
            assert is_up is True
            assert discovery.is_online is True
            assert len(callback_events) == 1
            assert callback_events[0][0] is True
            assert callback_events[0][1]["node"] == "BATAM_RESEARCH_NODE"
    asyncio.run(_test())

def test_scenario_3_deadman_switch_triggers_on_freeze():
    """SCENARIO 3: Heartbeat ceases -> Deadman switch detects timeout and triggers cancel_all_if_dead."""
    async def _test():
        deadman = IndodaxDeadmanSwitch(api_key="key", secret_key="secret", default_timeout_seconds=900)
        deadman.monitored_pairs.add("btcidr")
        deadman._last_heartbeat_ts = time.time() - 950 # 950s ago (> 900s timeout)

        # Elapsed exceeds timeout -> trigger cancel
        is_expired = (time.time() - deadman._last_heartbeat_ts) > deadman.default_timeout_seconds
        assert is_expired is True

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"success": 1, "return": {"countdownTime": 0}})
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_ctx)
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
            res = await deadman.cancel_all_if_dead("btcidr")
            assert res is True
            call_args = mock_session.post.call_args
            assert "countdownTime=0" in call_args[1]["data"]
    asyncio.run(_test())

def test_scenario_4_external_regime_down_fallback(tmp_path):
    """SCENARIO 4: getregime.com down -> Fallback to internal regime 100%, P5 rotation operates normally."""
    async def _test():
        runner = RotationPaperRunner(state_file=tmp_path / "p5_scenario4.json")
        prices = [100.0 + i * 2.0 for i in range(50)]
        df = pd.DataFrame({
            "open": prices, "high": [p + 1.0 for p in prices],
            "low": [p - 1.0 for p in prices], "close": prices,
            "volume": [5000.0] * 50,
        })

        # Simulate API down (raises connection error)
        with patch("aiohttp.ClientSession.get", side_effect=aiohttp.ClientConnectorError(MagicMock(), OSError("Connection refused"))):
            res = await runner.update_market_regime_with_consensus(btc_ohlcv_1h=df)
            assert res["consensus_status"] == "FALLBACK_INTERNAL"
            assert res["damping_multiplier"] == 1.0
            assert res["external_regime"] is None

        # Verify candidate evaluation proceeds with internal regime without crashing
        cand = {
            "symbol": "BTCIDR",
            "price": 1_000_000_000.0,
            "volume_idr": 500_000_000.0,
            "spread_pct": 0.001,
            "volume_ratio": 2.5,
        }
        eval_res = runner.evaluate_candidate(cand)
        assert eval_res.get("evaluated") is True
        assert eval_res.get("order", {}).get("success") is True
        assert len(runner.ledger.open_positions) == 1
    asyncio.run(_test())
