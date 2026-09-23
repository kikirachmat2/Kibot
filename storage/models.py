"""
Module: storage.models
Author: KiBot V3 Team
Date: 2026-10-01

References:
[1] Rishabh-27-Devloper/trade-ai (2025). "SQLite Schema Architecture for Algorithmic Portfolio Accounting."
[2] SQLite Consortium (2024). "Write-Ahead Logging (WAL) and Concurrency Guarantees in Financial State Stores."
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,          -- 'manual_topup', 'manual_withdraw', 'system_event'
    asset TEXT NOT NULL,               -- 'IDR', 'BTC', etc.
    amount REAL NOT NULL,
    metadata_json TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT,
    pair TEXT NOT NULL,
    side TEXT NOT NULL,                -- 'BUY', 'SELL'
    order_type TEXT NOT NULL,          -- 'LIMIT'
    price REAL NOT NULL,
    amount REAL NOT NULL,
    fee REAL NOT NULL,
    fee_asset TEXT NOT NULL,
    is_paper INTEGER DEFAULT 1,        -- 1=Paper, 0=Live
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions (
    asset TEXT PRIMARY KEY,
    amount REAL NOT NULL DEFAULT 0.0,
    cost_basis_idr REAL NOT NULL DEFAULT 0.0,
    total_invested_idr REAL NOT NULL DEFAULT 0.0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    total_equity_idr REAL NOT NULL,
    cash_idr REAL NOT NULL,
    allocations_json TEXT NOT NULL,    -- JSON breakdown of asset percentages
    regime_phase TEXT,
    is_paper INTEGER DEFAULT 1,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(timestamp);
CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON portfolio_snapshots(timestamp);
"""
