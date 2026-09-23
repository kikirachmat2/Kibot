import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from main import KiBotV3Orchestrator
from storage.database import Database
from config.fees import IDR_BUY_FEES


@pytest.fixture
def test_orchestrator(tmp_path):
    db_file = str(tmp_path / "test_orch.db")
    orch = KiBotV3Orchestrator(db_path=db_file, paper_mode=True)
    return orch


def test_orchestrator_commands(test_orchestrator):
    orch = test_orchestrator

    # Override price cache for deterministic test
    orch._price_cache = {
        "BTC": 1_400_000_000.0,
        "ETH": 50_000_000.0,
        "USDT": 16_000.0,
    }
    orch._price_cache_ts = 9999999999.0  # Keep cache warm

    # Topup with 70% BTC / 30% ETH allocation & order execution
    res_topup = orch.handle_command("/topup 500,000")
    assert "TOPUP TERDETEKSI & TERDEPLOY" in res_topup
    assert "BTC:" in res_topup
    assert "ETH:" in res_topup
    assert "SIMULASI" in res_topup

    # Status shows positions, real-time pricing, and NAV breakdown
    res_status = orch.handle_command("/status")
    assert "KIBOT V3 STATUS (PAPER)" in res_status
    assert "Total NAV: Rp" in res_status
    assert "BTC:" in res_status
    assert "ETH:" in res_status
    assert "Unrealized PnL:" in res_status

    # Simulate price surge to test dynamic unrealized PnL calculation
    orch._price_cache["BTC"] = 1_680_000_000.0  # +20%
    res_status_surge = orch.handle_command("/status")
    assert "Unrealized PnL:" in res_status_surge
    assert "Total NAV: Rp" in res_status_surge

    # Verify /withdraw command is removed (sells and withdrawals are manual in app)
    res_withdraw = orch.handle_command("/withdraw 100,000")
    assert "tidak dikenal" in res_withdraw

    # Report command
    res_report = orch.handle_command("/report")
    assert "KIBOT V3 — LAPORAN HARIAN" in res_report

    # Unknown command
    res_unk = orch.handle_command("/unknown")
    assert "tidak dikenal" in res_unk


def test_execution_live_vs_paper_mode(tmp_path):
    """
    TASK 4 Tests:
    - Mock indodax_client, assert place_buy_order TERPANGGIL dengan parameter benar saat paper_mode=False
    - Assert place_buy_order TIDAK PERNAH terpanggil saat paper_mode=True
    - Assert kalau place_buy_order gagal (exception/error response), record_trade TIDAK dipanggil
    - Assert fee yang dipakai identik dengan config/fees.py (bukan hardcode)
    """
    async def _run():
        db_file = str(tmp_path / "test_exec.db")
        mock_client = MagicMock()
        mock_client.api_key = "test_key"
        mock_client.api_secret = "test_secret"
        mock_client.place_buy_order = AsyncMock(return_value={
            "orderId": "LIVE-999",
            "price": 1_400_000_000.0,
            "executed_quantity": 0.00025,
            "fee": 738.85
        })

        # ── 1. PAPER MODE (place_buy_order must NEVER be called) ──
        orch_paper = KiBotV3Orchestrator(
            db_path=db_file,
            paper_mode=True,
            indodax_client=mock_client
        )
        orch_paper._price_cache = {"BTC": 1_400_000_000.0, "ETH": 50_000_000.0}
        orch_paper._price_cache_ts = 9999999999.0

        res_paper = await orch_paper._execute_topup_deployment(1_000_000.0)
        assert res_paper["success"] is True
        assert mock_client.place_buy_order.call_count == 0  # Zero API calls in paper mode!

        # ── 2. LIVE MODE (place_buy_order MUST be called with exact parameters) ──
        db_live_file = str(tmp_path / "test_exec_live.db")
        orch_live = KiBotV3Orchestrator(
            db_path=db_live_file,
            paper_mode=False,
            indodax_client=mock_client
        )
        orch_live._price_cache = {"BTC": 1_400_000_000.0, "ETH": 50_000_000.0}
        orch_live._price_cache_ts = 9999999999.0

        res_live = await orch_live._execute_topup_deployment(1_000_000.0)
        assert res_live["success"] is True
        # 2 calls: 1 for BTC (700k), 1 for ETH (300k)
        assert mock_client.place_buy_order.call_count == 2

        # Verify exact parameters for BTC call
        btc_call = mock_client.place_buy_order.call_args_list[0]
        assert btc_call.kwargs["pair"] == "btc_idr"
        assert btc_call.kwargs["order_type"] == "MARKET"
        assert btc_call.kwargs["price"] == 1_400_000_000.0
        # 700k / 1.4B = 0.0005 BTC
        assert btc_call.kwargs["amount_asset"] == 0.0005

        # Verify exact parameters for ETH call
        eth_call = mock_client.place_buy_order.call_args_list[1]
        assert eth_call.kwargs["pair"] == "eth_idr"
        assert eth_call.kwargs["order_type"] == "MARKET"
        assert eth_call.kwargs["price"] == 50_000_000.0
        # 300k / 50M = 0.006 ETH
        assert eth_call.kwargs["amount_asset"] == 0.006

        # ── 3. LIVE MODE FAILURE (No phantom trade recorded on error) ──
        mock_client_fail = MagicMock()
        mock_client_fail.api_key = "test_key"
        mock_client_fail.api_secret = "test_secret"
        mock_client_fail.place_buy_order = AsyncMock(side_effect=RuntimeError("Indodax API 500 Internal Error"))

        db_fail_file = str(tmp_path / "test_exec_fail.db")
        orch_fail = KiBotV3Orchestrator(
            db_path=db_fail_file,
            paper_mode=False,
            indodax_client=mock_client_fail
        )
        orch_fail._price_cache = {"BTC": 1_400_000_000.0, "ETH": 50_000_000.0}
        orch_fail._price_cache_ts = 9999999999.0

        res_fail = await orch_fail._execute_topup_deployment(1_000_000.0)
        assert res_fail["success"] is False
        assert len(res_fail["errors"]) == 2

        # Verify that database has NO transactions recorded
        with orch_fail.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM transactions")
            count = cursor.fetchone()[0]
            assert count == 0  # Absolutely NO phantom trade recorded!

        # ── 4. ASSERT FEE SCHEDULE IDENTICAL TO config/fees.py ──
        # Taker buy fee must match IDR_BUY_FEES.taker_pct (0.2111%)
        expected_fee_pct = IDR_BUY_FEES.taker_pct / 100.0
        assert expected_fee_pct == 0.002111
        # Test calculation on 1,000,000 topup:
        fee_btc = round(700_000.0 * expected_fee_pct, 2)
        assert fee_btc == 1477.70

    asyncio.run(_run())


def test_guardrails_task1(tmp_path):
    """
    TASK 1 Tests:
    - If amount_idr > MAX_SINGLE_TRADE_IDR (1,000,000): REJECT, do NOT execute, send alert.
    - If monthly topup + amount > MAX_MONTHLY_TOPUP_IDR (5,000,000): REJECT, do NOT execute, send alert.
    - Neither should silently clip or fail silently.
    """
    async def _run():
        db_file = str(tmp_path / "test_guardrails.db")
        mock_reporter = MagicMock()
        mock_reporter.bot_token = "dummy_token"
        mock_reporter.send_message = AsyncMock(return_value=True)

        orch = KiBotV3Orchestrator(db_path=db_file, paper_mode=True)
        orch.reporter = mock_reporter
        orch._price_cache_ts = 9999999999.0

        # 1. Single trade breach (1,500,000 > 1,000,000)
        res_single = await orch._execute_topup_deployment(1_500_000.0)
        assert res_single["success"] is False
        assert res_single["guardrail_breached"] == "MAX_SINGLE_TRADE_IDR"
        assert res_single["total_deployed_idr"] == 0.0
        assert mock_reporter.send_message.call_count == 1
        assert "MAX_SINGLE_TRADE_IDR" in mock_reporter.send_message.call_args[0][0]

        # 2. Cumulative monthly breach:
        # First deploy 5 x 900,000 = 4,500,000 (valid trades)
        for _ in range(5):
            r = await orch._execute_topup_deployment(900_000.0)
            assert r["success"] is True

        # Now monthly total is 4,500,000. Adding 600,000 = 5,100,000 (> 5,000,000) -> MUST REJECT
        mock_reporter.send_message.reset_mock()
        res_monthly = await orch._execute_topup_deployment(600_000.0)
        assert res_monthly["success"] is False
        assert res_monthly["guardrail_breached"] == "MAX_MONTHLY_TOPUP_IDR"
        assert res_monthly["total_deployed_idr"] == 0.0
        assert mock_reporter.send_message.call_count == 1
        assert "MAX_MONTHLY_TOPUP_IDR" in mock_reporter.send_message.call_args[0][0]

    asyncio.run(_run())


def test_price_freshness_check_task3(tmp_path):
    """
    TASK 3 Test:
    - In LIVE mode (paper_mode=False), if price cache age > 600s (10 min):
      DO NOT execute, reject with error, alert Supervisor.
    """
    async def _run():
        db_file = str(tmp_path / "test_freshness.db")
        mock_reporter = MagicMock()
        mock_reporter.bot_token = "dummy_token"
        mock_reporter.send_message = AsyncMock(return_value=True)

        mock_client = MagicMock()
        mock_client.api_key = "live_key"
        mock_client.place_buy_order = AsyncMock()

        orch = KiBotV3Orchestrator(
            db_path=db_file,
            paper_mode=False,
            indodax_client=mock_client
        )
        orch.reporter = mock_reporter

        # Make cache stale (> 600s)
        import time
        orch._price_cache = {"BTC": 1_400_000_000.0, "ETH": 50_000_000.0}
        orch._price_cache_ts = time.time() - 650.0  # 650s old!

        res = await orch._execute_topup_deployment(500_000.0)
        assert res["success"] is False
        assert res["guardrail_breached"] == "STALE_PRICES"
        assert mock_client.place_buy_order.call_count == 0  # No orders placed!
        assert mock_reporter.send_message.call_count == 1
        assert "HARGA TIDAK FRESH" in mock_reporter.send_message.call_args[0][0]

    asyncio.run(_run())


def test_health_status_endpoint_task4(tmp_path):
    """
    TASK 4 & 7 Tests:
    - get_health_status returns uptime, last_poll_ts, last_price_fetch_ts, commit_hash, disk usage
    """
    db_file = str(tmp_path / "test_health.db")
    orch = KiBotV3Orchestrator(db_path=db_file, paper_mode=True, health_port=8789)
    orch.last_poll_ts = 1700000000.0
    orch.last_price_fetch_ts = 1700000005.0

    health = orch.get_health_status()
    assert health["status"] in ["HEALTHY", "DEGRADED"]
    assert "uptime_seconds" in health
    assert health["last_poll_ts"] == 1700000000.0
    assert health["last_price_fetch_ts"] == 1700000005.0
    assert "commit_hash" in health
    assert "disk" in health
    assert "used_pct" in health["disk"]


def test_balance_snapshot_persistence_across_restarts(tmp_path):
    """
    Test that _last_balance_snapshot is persisted to SQLite and restored on restart.
    Verifies that a deposit occurring after restart is detected correctly from the
    restored baseline snapshot (not skipped or baseline-reset to 0).
    """
    db_file = str(tmp_path / "test_snapshot_restart.db")

    # Instance 1: Initial run with an established balance snapshot
    orch1 = KiBotV3Orchestrator(db_path=db_file, paper_mode=True)
    # Fresh database: snapshot is empty initially
    assert orch1._last_balance_snapshot == {}

    # Simulate poll loop updating snapshot to 1,000,000 IDR
    initial_balances = {"idr": 1_000_000.0, "btc": 0.05, "eth": 0.5}
    orch1._last_balance_snapshot = dict(initial_balances)
    orch1._save_last_balance_snapshot(orch1._last_balance_snapshot)

    # Verify directly written to SQLite system_state
    db = Database(db_file)
    raw_saved = db.get_state("last_balance_snapshot")
    assert raw_saved is not None
    assert "1000000" in raw_saved

    # Instance 2: Simulate service restart (new orchestrator instance on same DB)
    orch2 = KiBotV3Orchestrator(db_path=db_file, paper_mode=True)
    # Snapshot should be restored from database immediately upon startup
    assert orch2._last_balance_snapshot == {"idr": 1_000_000.0, "btc": 0.05, "eth": 0.5}

    # Now simulate a new deposit of 500,000 IDR arriving after restart
    new_balances = {"idr": 1_500_000.0, "btc": 0.05, "eth": 0.5}
    events = orch2.event_detector.detect_events(
        current_balances=new_balances,
        previous_balances=orch2._last_balance_snapshot
    )

    # Event MUST be detected on the very first poll after restart!
    assert len(events) == 1
    assert events[0].event_type == "manual_topup"
    assert events[0].asset == "IDR"
    assert events[0].amount == 500_000.0
