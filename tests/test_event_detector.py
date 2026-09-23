"""
Unit tests for EventDetector.
"""

import json
import pytest
from storage.database import Database
from core.event_detector import EventDetector, AccountEvent


def test_event_detector_topup(tmp_path):
    db_file = str(tmp_path / "test_events.db")
    db = Database(db_file)
    detector = EventDetector(db)

    prev_bal = {"idr": 100000.0, "btc": 0.01}
    curr_bal = {"idr": 600000.0, "btc": 0.01}

    events = detector.detect_events(curr_bal, prev_bal)
    assert len(events) == 1
    assert events[0].event_type == "manual_topup"
    assert events[0].amount == 500000.0

    # Verify persisted in database
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT event_type, amount FROM events")
        row = cursor.fetchone()
        assert row[0] == "manual_topup"
        assert row[1] == 500000.0


def test_event_detector_withdraw(tmp_path):
    db_file = str(tmp_path / "test_events.db")
    db = Database(db_file)
    detector = EventDetector(db)

    prev_bal = {"idr": 500000.0, "btc": 0.01}
    curr_bal = {"idr": 200000.0, "btc": 0.01}

    events = detector.detect_events(curr_bal, prev_bal)
    assert len(events) == 1
    assert events[0].event_type == "manual_withdraw"
    assert events[0].amount == 300000.0


def test_event_detector_no_event_on_bot_trade(tmp_path):
    db_file = str(tmp_path / "test_events.db")
    db = Database(db_file)
    detector = EventDetector(db)
    detector.set_trade_happened(True)

    prev_bal = {"idr": 500000.0, "btc": 0.01}
    curr_bal = {"idr": 100000.0, "btc": 0.0128}

    events = detector.detect_events(curr_bal, prev_bal)
    assert len(events) == 0


def test_event_detector_format_alert():
    topup_ev = AccountEvent(
        event_type="manual_topup",
        asset="IDR",
        amount=500000.0,
        metadata={}
    )
    alert = EventDetector.format_telegram_alert(topup_ev)
    assert "TOPUP TERDETEKSI" in alert
    assert "500,000" in alert


def test_event_detector_manual_crypto_sale(tmp_path):
    db_file = str(tmp_path / "test_events.db")
    db = Database(db_file)
    detector = EventDetector(db)

    prev_bal = {"idr": 100000.0, "btc": 0.05}
    curr_bal = {"idr": 100000.0, "btc": 0.03}  # 0.02 BTC sold manually in app

    events = detector.detect_events(curr_bal, prev_bal)
    assert len(events) == 1
    assert events[0].event_type == "manual_crypto_sale"
    assert events[0].asset == "BTC"
    assert events[0].amount == 0.02

    disposal_info = {
        "estimated_price": 1_420_000_000.0,
        "estimated_realized_pnl_idr": 8_400_000.0,
    }
    alert = EventDetector.format_telegram_alert(events[0], disposal_info=disposal_info)
    assert "PENJUALAN / WITHDRAWAL MANUAL TERDETEKSI" in alert
    assert "0.020000 BTC" in alert
    assert "ESTIMASI" in alert
