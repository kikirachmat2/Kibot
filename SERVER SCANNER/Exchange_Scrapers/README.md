# [Module] Exchange Scrapers (The Global Sensor Network)

This directory contains the "Eyes" of the system. Each script monitors a specific exchange in real-time to detect price pumps and volume anomalies.

## Key Files

### 1. `ki_binance_scanner.py` (Primary Sensor)
- **Weight**: 0.16 (Highest)
- **Role**: Detects early movements on the world's largest exchange to predict lag-behind pumps on Indodax.

### 2. `multi_scanner_engine.py` (The Hub)
- **Role**: Aggregates all incoming scraper data.
- **Responsibilities**:
    - Calculates the **Multi-Scanner Confidence (MSC)** score.
    - Filters out "Fake Pumps" (e.g., MEXC-only movements).
    - Relays the final "ENTRY" signal to the Brain.

### 3. Individual Scrapers
- `ki_bybit_scanner.py`, `ki_kucoin_scanner.py`, `ki_okx_scanner.py`, etc.
- Each script is optimized for the specific API of the target exchange.

### 4. `ki_whale_scanner.py`
- **Role**: Monitors large on-chain transactions and "Whale" alerts to find long-term trends.

## How to Deploy
These scrapers are typically deployed as systemd services using the templates in the `Deployment/` folder. They communicate with the Brain via UDP (Port 9999).

## Scaling
To add a new exchange, simply clone `ki_scanner_base.py` and implement the `fetch_ticker` method for the new exchange.
