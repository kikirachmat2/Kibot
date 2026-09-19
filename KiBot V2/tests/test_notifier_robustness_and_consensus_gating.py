import asyncio
import logging
import os
import shutil
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, patch

from config import settings
from storage.async_logger import SecretRedactingFilter, TELEGRAM_TOKEN_REGEX
from notifications.telegram_notifier import TelegramNotifier
from paper_rotation_runner import RotationPaperRunner
from council.regime_detector import MarketRegime

def test_secret_redacting_filter():
    filter_obj = SecretRedactingFilter(key="my_secret_key_12345", secret="my_super_secret_indodax", tg_token="REDACTED_TELEGRAM_TOKEN")
    
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
