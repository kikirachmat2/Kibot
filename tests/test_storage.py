"""
Tests for KiBot V3 Storage Layer and Configuration.
"""

import os
import pytest
from storage.database import Database
from config.settings import Settings


def test_database_wal_mode(tmp_path):
    test_db = str(tmp_path / "test_kibot.db")
    db = Database(test_db)
    assert db.is_wal_enabled() is True


def test_database_tables_created(tmp_path):
    test_db = str(tmp_path / "test_kibot.db")
    db = Database(test_db)
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        
    expected = {"events", "transactions", "positions", "portfolio_snapshots"}
    assert expected.issubset(tables)


def test_settings_defaults():
    s = Settings()
    assert s.PAPER_MODE is True
    assert s.EVENT_POLLING_INTERVAL == 180
    assert s.TARGET_ALLOCATION["BTC"] == 0.70
    assert s.TARGET_ALLOCATION["ETH"] == 0.30
