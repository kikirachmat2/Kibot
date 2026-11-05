"""
intelligence/supabase_client.py - Secondary Backup & Alternative Mirror for KiBot V3
ROLE: Asynchronous offsite backup & alternative mirror ONLY.
Local SQLite (kibot_v3.db) remains the primary single source of truth for all trades,
balances, nonces, and order executions.
"""

import os
import json
import logging
from typing import Dict, Any, Optional
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None

logger = logging.getLogger("KiBotSupabase")


def get_pg_connection():
    if not psycopg2:
        return None

    host = os.getenv("SUPABASE_DB_HOST", "aws-0-ap-southeast-1.pooler.supabase.com")
    port = int(os.getenv("SUPABASE_DB_PORT", "5432"))
    dbname = os.getenv("SUPABASE_DB_NAME", "postgres")
    user = os.getenv("SUPABASE_DB_USER", "postgres.zqgzrkuhemknqnlfdgjr")
    password = os.getenv("SUPABASE_DB_PASS", "ui9nqBbLKqGSv2Px")

    try:
        return psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            connect_timeout=3,
            sslmode="require"
        )

    except Exception as e:
        logger.warning(f"⚠️ Supabase PostgreSQL connection failed: {e}")
        return None


def send_fleet_heartbeat(status: str = "ONLINE", metrics: Optional[Dict[str, Any]] = None) -> bool:
    """Updates live heartbeat and metrics in Supabase."""
    conn = get_pg_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fleet_telemetry (bot_id, bot_name, role, status, last_heartbeat, host, metrics, updated_at)
                VALUES (%s, %s, %s, %s, NOW(), %s, %s, NOW())
                ON CONFLICT (bot_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    last_heartbeat = NOW(),
                    metrics = EXCLUDED.metrics,
                    updated_at = NOW();
            """, (
                "kibot",
                "KiBot V3 Indodax Trader",
                "ASSET_GROWTH",
                status,
                "SG1 Cloud",
                json.dumps(metrics or {})
            ))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error sending KiBot heartbeat: {e}")
        return False
    finally:
        conn.close()


def record_kibot_trade(
    pair: str,
    action: str,
    amount_idr: float,
    price_idr: float,
    crypto_units: float,
    volatility_factor: float = 1.0,
    fear_greed_score: Optional[int] = None,
    total_equity_idr: Optional[float] = None,
    cash_idr: Optional[float] = None,
    allocations: Optional[Dict[str, Any]] = None,
    tx_hash_or_id: Optional[str] = None
) -> Optional[int]:
    """Records trade execution to Supabase and publishes an event to tri_party_bus."""
    conn = get_pg_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO kibot_portfolio_ledger (
                    pair, action, amount_idr, price_idr, crypto_units,
                    volatility_factor, fear_greed_score, total_equity_idr,
                    cash_idr, allocations, execution_status, tx_hash_or_id,
                    timestamp, created_at
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, 'COMPLETED', %s,
                    NOW(), NOW()
                )
                RETURNING id;
            """, (
                pair, action, amount_idr, price_idr, crypto_units,
                volatility_factor, fear_greed_score, total_equity_idr,
                cash_idr, json.dumps(allocations or {}), tx_hash_or_id
            ))
            row = cur.fetchone()
            trade_id = row[0] if row else None

            # Publish event to tri_party_bus so Zura can broadcast to War Room
            if trade_id:
                cur.execute("""
                    INSERT INTO tri_party_bus (sender, recipient, topic, action, payload, telegram_broadcast, status, created_at)
                    VALUES ('kibot', 'zura', 'trade', %s, %s, true, 'PENDING', NOW());
                """, (action, json.dumps({
                    "trade_id": trade_id,
                    "pair": pair,
                    "action": action,
                    "amount_idr": amount_idr,
                    "price_idr": price_idr,
                    "crypto_units": crypto_units,
                    "volatility_factor": volatility_factor,
                    "fear_greed_score": fear_greed_score,
                    "total_equity_idr": total_equity_idr,
                    "cash_idr": cash_idr
                })))
            conn.commit()
            return trade_id
    except Exception as e:
        logger.error(f"Error recording KiBot trade to Supabase: {e}")
        return None
    finally:
        conn.close()

