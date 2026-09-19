import asyncio
import logging
import os
import shutil
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, patch
import time

from config import settings
from storage.async_logger import SecretRedactingFilter, TELEGRAM_TOKEN_REGEX
from notifications.telegram_notifier import TelegramNotifier
from paper_rotation_runner import RotationPaperRunner
from council.regime_detector import MarketRegime

def test_secret_redacting_filter():
    filter_obj = SecretRedactingFilter(key="my_secret_key_12345", secret="my_super_secret_indodax", tg_token="9876543210:AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqR")
    
    # 1. Arbitrary Telegram token pattern
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=10,
        msg="Connecting with token=1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789 to bot",
        args=(), exc_info=None
    )
    filter_obj.filter(record)
    assert "<REDACTED>" in record.msg
    assert "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789" not in record.msg

    # 2. Configured secret redacting
    record2 = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=20,
        msg="Using key my_secret_key_12345 and secret my_super_secret_indodax",
        args=(), exc_info=None
    )
    filter_obj.filter(record2)
    assert record2.msg == "Using key <REDACTED> and secret <REDACTED>"

def test_telegram_fallback_3x_failures(tmp_path):
    async def _run():
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        notifier = TelegramNotifier(bot_token="1111111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", chat_id="123456789")
        
        # Mock post to fail 3 times
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.text.return_value = "Internal Server Error"
        
        with patch.object(settings, "LOG_DIR", log_dir), \
             patch.object(notifier, "_dispatch_fallback_webhook", new_callable=AsyncMock) as mock_webhook, \
             patch("aiohttp.ClientSession.post") as mock_post:
            
            mock_post.return_value.__aenter__.return_value = mock_resp
            
            # 1st fail
            res1 = await notifier.send_alert("TEST_FAIL", "Fail 1", "Message 1", force=True)
            assert res1 is False
            assert notifier._consecutive_failures == 1
            assert not (log_dir / "telegram_failures.log").exists()
            
            # 2nd fail
            res2 = await notifier.send_alert("TEST_FAIL", "Fail 2", "Message 2", force=True)
            assert res2 is False
            assert notifier._consecutive_failures == 2
            assert not (log_dir / "telegram_failures.log").exists()
            
            # 3rd fail -> triggers local fallback log!
            res3 = await notifier.send_alert("TEST_FAIL", "Fail 3", "Message 3", force=True)
            assert res3 is False
            assert notifier._consecutive_failures == 3
            assert (log_dir / "telegram_failures.log").exists()
            
            content = (log_dir / "telegram_failures.log").read_text()
            assert "FAILURE #3" in content
            assert "Fail 3" in content

    asyncio.run(_run())

def test_p5_consensus_conflict_blocks_entry(tmp_path):
    runner = RotationPaperRunner(state_file=tmp_path / "p5_test.json")


    
    candidate = {
        "symbol": "BTCIDR",
        "price": 1_000_000_000.0,
        "volume_idr": 500_000_000.0,
        "spread_pct": 0.001,
        "volume_ratio": 2.5,
    }
    
    # Case 1: FULL_CONFLICT -> Must block entry
    regime_conflict = {
        "regime": MarketRegime.BULL,
        "btc_dominance_trend_7h": 1.0,
        "consensus_status": "FULL_CONFLICT",
        "damping_multiplier": 0.5,
    }
    res_conflict = runner.evaluate_candidate(candidate, regime_override=regime_conflict)
    assert res_conflict["evaluated"] is False
    assert res_conflict["reason"] == "external_regime_full_conflict_block"
    
    # Case 2: Agreement with damping multiplier -> Allowed and sized with damping
    regime_ok = {
        "regime": MarketRegime.BULL,
        "btc_dominance_trend_7h": 1.0,
        "consensus_status": "PARTIAL_DISAGREEMENT",
        "damping_multiplier": 0.85,
    }
    res_ok = runner.evaluate_candidate(candidate, regime_override=regime_ok)
    assert res_ok["evaluated"] is True
    assert "BTCIDR" in runner.ledger.open_positions
    pos = runner.ledger.open_positions["BTCIDR"]
    # 50,000 * 0.85 = 42,500 IDR
    assert abs(pos.cost_idr - 42500.0) < 1.0


def test_telegram_chat_whitelist_and_rate_limit():
    async def _run():
        notifier = TelegramNotifier(
            bot_token="1111111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            chat_id="123456789",
            allowed_chat_ids={123456789}
        )

        # 1. Whitelist validation
        assert notifier.is_chat_id_allowed("123456789") is True
        assert notifier.is_chat_id_allowed(123456789) is True
        assert notifier.is_chat_id_allowed("999999999") is False

        # Attempt sending to unauthorized chat_id
        res_blocked = await notifier.send_message("999999999", "Test unauthorized")
        assert res_blocked is False

        res_alert_blocked = await notifier.send_alert("TEST", "Title", "Msg", chat_id="999999999")
        assert res_alert_blocked is False

        # 2. Rate limit validation (Max 100/hr)
        now = time.time()
        for _ in range(100):
            notifier._record_sent_timestamp(now)
        
        assert notifier._check_rate_limit(now) is False
        res_rate_limited = await notifier.send_message("123456789", "Test 101")
        assert res_rate_limited is False

        # 3. Anomaly detection (5+ messages in 1 min)
        with patch.object(notifier, "_dispatch_fallback_webhook", new_callable=AsyncMock) as mock_webhook:
            with patch.object(settings, "TELEGRAM_FALLBACK_WEBHOOK", "https://discord.com/api/webhooks/dummy"):
                await notifier._check_and_alert_anomaly(now)
                assert mock_webhook.call_count == 1
                call_args = mock_webhook.call_args[1]
                assert call_args["event_type"] == "TELEGRAM_BURST_ANOMALY"

        # 4. Outbound message hash log verification
        log_file = Path("logs/sent_messages.jsonl")
        if log_file.exists():
            log_file.unlink()
        notifier._log_sent_message(123456789, "Verification test message")
        assert log_file.exists()
        import json
        with open(log_file) as f:
            entry = json.loads(f.readline())
            assert entry["chat_id"] == "123456789"
            assert entry["length"] == len("Verification test message")
            assert "hash" in entry

    asyncio.run(_run())
