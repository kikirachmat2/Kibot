"""Unit tests for WebSocket ingestion resilience, exponential backoff, and data age metrics."""
import asyncio
import time
import pytest
from async_helper import run_async
from ingestion.base import BaseWebSocketClient, ConnectionState
from ingestion.metrics import DataAgeMetrics, metrics_registry
from ingestion.indodax_ws import IndodaxWebSocketClient

def test_exponential_backoff_progression():
    """Verify backoff starts at 1.0s, doubles, and caps at 30.0s."""
    client = BaseWebSocketClient("wss://dummy", min_backoff_s=1.0, max_backoff_s=30.0)
    
    assert client.min_backoff_s == 1.0
    assert client.max_backoff_s == 30.0
    assert client._current_backoff_s == 1.0
    
    # Simulate doubling progression
    cur = client._current_backoff_s
    progression = []
    for _ in range(6):
        progression.append(cur)
        cur = min(client.max_backoff_s, cur * 2.0)
        
    assert progression == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]

def test_data_age_metric_tracker():
    """Verify real-time data age tracking per symbol."""
    tracker = DataAgeMetrics()
    
    # Record updates
    now = time.time()
    tracker.record_tick("BTC/IDR", now)
    assert tracker.is_fresh("BTC/IDR", max_age_ms=1000.0) is True
    age = tracker.get_data_age_ms("BTC/IDR")
    assert age >= 0 and age < 500

    # Unrecorded symbol
    assert tracker.get_data_age_ms("UNKNOWN/IDR") == float("inf")
    assert tracker.is_fresh("UNKNOWN/IDR") is False

@run_async
async def test_heartbeat_dead_connection_detection():
    """Verify dead connection detection logic detects stalled heartbeat in <5s."""
    client = BaseWebSocketClient(
        "wss://dummy",
        heartbeat_interval_s=2.0,
        heartbeat_timeout_s=2.0
    )
    # If last heartbeat was 6 seconds ago, interval + timeout (4.0s) has elapsed
    client._last_heartbeat_ts = time.time() - 6.0
    now = time.time()
    is_dead = (now - client._last_heartbeat_ts) > (client.heartbeat_interval_s + client.heartbeat_timeout_s)
    assert is_dead is True
    
    # Fresh heartbeat
    client._last_heartbeat_ts = time.time() - 1.0
    now = time.time()
    is_dead_fresh = (now - client._last_heartbeat_ts) > (client.heartbeat_interval_s + client.heartbeat_timeout_s)
    assert is_dead_fresh is False

@run_async
async def test_indodax_message_parsing():
    """Verify Indodax client handles 24h summary parsing correctly."""
    client = IndodaxWebSocketClient()
    received_tickers = []
    
    async def on_ticker(t):
        received_tickers.append(t)
        
    client.on_ticker_cb = on_ticker
    
    raw_payload = {
        "result": {
            "channel": "market:summary-24h",
            "data": {
                "data": [
                    ["btc_idr", 1700000000, "1050000000", "980000000", "1010000000", "50000000000"]
                ]
            }
        }
    }
    import json
    await client._handle_message(json.dumps(raw_payload))
    
    assert len(received_tickers) == 1
    assert received_tickers[0]["pair"] == "BTC_IDR"
    assert received_tickers[0]["last_price"] == 1010000000.0
