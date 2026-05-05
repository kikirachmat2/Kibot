# 👁️ SERVER_SCANNER (Sensory Node) - Trinity v9.1

## Overview
The Scanner collection acts as the **"Eyes"** of the KiBot ecosystem. These nodes function as high-frequency sensory arrays that stream raw market data from 20+ global exchanges directly to the **Batam Control Plane**.

## Role & Responsibility
1. **Sensory Mesh**: Fetch tickers and orderbook depth from Binance, Bybit, MEXC, Indodax, etc.
2. **Polymarket Integration**: Specialized scanner for prediction markets to feed the Arbitrator.
3. **Bandwidth Optimization**: Dynamically filters data based on Indodax-listed assets.
4. **Data Integrity**: Streams are signed via HMAC-SHA256 for secure Inbound communication.

## Core Scrapers
- **Exchange_Scrapers/**: Contains 20+ specialized exchange modules.
- **ki_scanner_base.py**: The foundation for all sensory logic.
- **ki_global_scanner_mesh.py**: Orchestrates the entire scanner cluster.

> [!NOTE]
> **Optimization Update**: To preserve RAM on the 1GB Scanner node, 10 "Tier-2" scrapers (Mexc, Phemex, Gate.io, Kucoin, etc.) have been disabled. Only Tier-1 scrapers (Binance, Bybit, OKX, Upbit) are active.

## Deployment & systemd
- `kibot-scanner-mesh.service`: Global orchestrator for all scrapers.
- `kibot-scanner@.service`: Template for running individual exchange instances.

## Protocol
- **Outbound**: UDP Packets (JSON) to Batam Port 9999.
- **Frequency**: Configurable, default 5-10s polling interval.
