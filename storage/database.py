"""
Module: storage.database
Author: KiBot V3 Team
Date: 2026-10-01

SQLite WAL mode replaces V2's JSON flat-file state.

References:
[1] Hipp, D. R. (2024). "SQLite: Write-Ahead Logging (WAL) Mode Specifications". https://sqlite.org/wal.html. Accessed: 2026-09-20.
[2] V2 Audit (commit 323808e) — V2 state corruption bug: restore_state() failed to restore cash_idr=0.0. SQLite ACID transactions prevent same class.
    Ref: https://github.com/kikirachmat2/Kibot/blob/main/KiBot%20V2/executor/virtual_ledger.py
[3] Python Software Foundation (2025). "sqlite3 — DB-API 2.0 interface for SQLite databases". https://docs.python.org/3/library/sqlite3.html. Accessed: 2026-09-20.
"""

import sqlite3
import os
from typing import Optional
from storage.models import SCHEMA_SQL


class Database:
    def __init__(self, db_path: str = "data/kibot_v3.db"):
        self.db_path = db_path
        self._ensure_directory()
        self.init_db()

    def _ensure_directory(self):
        dir_name = os.path.dirname(self.db_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for high concurrency read/write
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    def is_wal_enabled(self) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode;")
            mode = cursor.fetchone()[0]
            return mode.upper() == "WAL"

    def set_state(self, key: str, value: str):
        """Persist a key-value pair into system_state table."""
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO system_state (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (key, value)
            )
            conn.commit()

    def get_state(self, key: str) -> Optional[str]:
        """Retrieve a value by key from system_state table."""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM system_state WHERE key = ?;",
                (key,)
            ).fetchone()
            return row["value"] if row else None
