"""
Test Malformed WebSocket Payload Resilience (C.2).
Proves that Indodax and Binance WebSocket listeners survive corrupted, null,
NaN, missing fields, and malformed structures without throwing uncaught exceptions
or killing the event loop.
"""
import asyncio
import json
import pytest
from async_helper import run_async
from ingestion.indodax_ws import IndodaxWebSocketClient
from ingestion.binance_ws import BinanceWebSocketClient

@run_async
async def test_indodax_malformed_payload_resilience():
    """
    Feeds numerous corrupted payloads into Indodax WebSocket handler
    and proves it continues processing valid messages without crashing.
    """
    valid_tickers_received = []
    
    async def on_ticker(tick):
        valid_tickers_received.append(tick)

    client = IndodaxWebSocketClient(token="test_token")
    client.on_ticker_cb = on_ticker

    # 1. Totally invalid JSON
    await client._handle_message("NOT_JSON_STRING_AT_ALL {{{")

    # 2. Empty JSON object
    await client._handle_message("{}")

    # 3. Malformed channel / data structure
    await client._handle_message(json.dumps({"result": "invalid_result_type"}))
    await client._handle_message(json.dumps({"result": {"channel": "market:summary-24h", "data": "not_a_dict"}}))
    await client._handle_message(json.dumps({"result": {"channel": "market:summary-24h", "data": {"data": "not_a_list"}}}))

    # 4. Corrupted items in 24h summary
    corrupted_items_payload = {
        "result": {
            "channel": "market:summary-24h",
            "data": {
                "data": [
                    None,                                       # None item
                    [],                                         # Empty item
                    ["btc_idr"],                                # Short item (<5 elements)
                    [None, 1700000000, 1000, 900, 950],         # None pair
                    ["", 1700000000, 1000, 900, 950],           # Empty pair
                    ["eth_idr", 1700000000, 100, 90, "NaN"],    # NaN last price
                    ["sol_idr", 1700000000, 100, 90, None],     # None last price
                    ["ada_idr", 1700000000, 100, 90, -500],     # Negative price
                    ["doge_idr", "not_an_epoch", "inf", "-inf", 0], # Zero price
                ]
            }
        }
    }
    await client._handle_message(json.dumps(corrupted_items_payload))

    # All corrupted items must be skipped without any crash
    assert len(valid_tickers_received) == 0

    # 5. Now send a VALID payload right after all the garbage
    valid_payload = {
        "result": {
            "channel": "market:summary-24h",
            "data": {
                "data": [
                    ["btc_idr", 1700000000, "1050000000", "980000000", "1010000000", "50000000000"]
                ]
            }
        }
    }
    await client._handle_message(json.dumps(valid_payload))

    # Verify listener survived and successfully processed the valid message
    assert len(valid_tickers_received) == 1
    assert valid_tickers_received[0]["pair"] == "BTC_IDR"
    assert valid_tickers_received[0]["last_price"] == 1010000000.0
    assert valid_tickers_received[0]["volume_idr"] == 50000000000.0

@run_async
async def test_binance_malformed_payload_resilience():
    """
    Feeds corrupted payloads into Binance miniTicker handler
    and proves it continues processing valid messages without crashing.
    """
    valid_tickers_received = []

    async def on_mini(tick):
        valid_tickers_received.append(tick)

    client = BinanceWebSocketClient()
    client.on_mini_ticker_cb = on_mini

    # 1. Invalid JSON
    await client._handle_message("INVALID_JSON_STREAM")

    # 2. Not a list
    await client._handle_message(json.dumps({"error": "not a list"}))

    # 3. List with corrupted elements
    corrupted_list = [
        None,
        "string_item",
        {},                                         # Empty dict
        {"s": None, "c": "50000"},                  # None symbol
        {"s": "BTCUSDT", "c": "NaN"},               # NaN close price
        {"s": "BTCUSDT", "c": None},                # None close price
        {"s": "BTCUSDT", "c": "-1000"},             # Negative price
        {"s": "ETHBTC", "c": "0.05"},               # Non-USDT pair
        {"s": "SOLUSDT", "c": "200.5", "o": "NaN", "v": None}, # Valid price but NaN open/None vol
    ]
    await client._handle_message(json.dumps(corrupted_list))

    # SOLUSDT should safely fall back open=close and vol=0.0
    assert len(valid_tickers_received) == 1
    assert valid_tickers_received[0]["symbol"] == "SOLUSDT"
    assert valid_tickers_received[0]["close"] == 200.5
    assert valid_tickers_received[0]["open"] == 200.5
    assert valid_tickers_received[0]["volume"] == 0.0

    # 4. Send pure valid payload
    valid_list = [
        {
            "s": "BTCUSDT",
            "c": "65000.50",
            "o": "64000.00",
            "h": "66000.00",
            "l": "63500.00",
            "v": "1234.5",
            "q": "80000000.0",
        }
    ]
    await client._handle_message(json.dumps(valid_list))

    assert len(valid_tickers_received) == 2
    assert valid_tickers_received[1]["symbol"] == "BTCUSDT"
    assert valid_tickers_received[1]["close"] == 65000.50
