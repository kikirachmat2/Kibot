# 👁️ [Module] Exchange Scrapers (Sensory Fleet)

This directory contains the high-frequency scrapers responsible for global market awareness.

## Architecture: Sensory Mesh
In Trinity v9.1, Scrapers no longer perform local filtering. They are "Dumb & Fast" sensory nodes that stream raw data to Batam.

## Critical Sensors
- **ki_binance_scanner_v2.py**: Optimized for WebSocket stream to capture micro-second movements.
- **ki_indodax_scanner.py**: Monitors local liquidity and IDR spread.
- **ki_indodax_smallcap_scanner.py**: [NEW v9.2] Detects volume spikes and OBI pumps on low-liquidity Indodax pairs.
- **ki_polymarket_full_scanner.py**: [NEW v9.2] Full-coverage prediction market scanner with confidence scoring and momentum detection.
- **ki_whale_scanner.py**: Monitors large exchange inflows/outflows.

## Core Foundation
- **ki_scanner_base.py**: The parent class. Handles HMAC signing of UDP packets and dynamic Indodax pair matching.
- **ki_global_scanner_mesh.py**: Orchestrates the entire fleet of scrapers to ensure 100% uptime and automatic failover.

## Data Protocol
- **Format**: JSON over UDP.
- **Security**: HMAC-SHA256 signing enabled by default.
- **Target**: Batam IP (Port 9999).
