# KiBot Scanner (Sensory Node)

## Overview
The Scanner collection acts as the **"Eyes"** of the KiBot ecosystem. In this lobotomized version, all local signal detection and filtering logic have been removed. The scanners now function as high-frequency sensory nodes that stream raw market data directly to the **Batam Control Plane**.

## Role & Responsibility
1. **Raw Data Streaming**: Fetch tickers from 20+ exchanges and stream them without filtering to Batam.
2. **Indodax Cross-Referencing**: Only data for coins listed on Indodax (dynamic fetching) is sent to optimize bandwidth.
3. **High Frequency**: Default polling interval is reduced to **5 seconds** for near real-time market awareness.
4. **Security**: All data streams are signed with HMAC-SHA256 to ensure Batam only trusts legitimate scanner nodes.

## Data Protocol (UDP Stream)
Scanners send `SENSORY_DATA_STREAM` packets via UDP:
```json
{
  "type": "SENSORY_DATA_STREAM",
  "node": "BINANCE | BYBIT | etc",
  "base_symbol": "BTC",
  "pair_indodax": "btc_idr",
  "price_usdt": 65000.0,
  "vol_usdt_24h": 100000000.0,
  "change_24h": 2.5,
  "change_1h": 0.5,
  "is_raw": true
}
```

## Architecture
- **ki_scanner_base.py**: The base class for all scanners. Handles the UDP streaming, signing, and Indodax pair matching.
- **multi_scanner_engine.py**: Orchestrates multiple exchange scrapers simultaneously.

## Deployment
Scanners should be deployed globally to minimize latency to exchange API endpoints. All nodes report back to the central `KIBOT_MANAGER_HOST` (Batam).
