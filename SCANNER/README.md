# [SCANNER] The Global Eyes

The Scanner network provides real-time market data across 20+ exchanges. It generates the Multi-Scanner Confidence (MSC) score that fuels the KiBot anomaly detection.

## Sub-components

### 1. [Exchange_Scrapers](file:///Users/kiki/Documents/Web%20Develop/KiBot/SCANNER/Exchange_Scrapers/)
Individual Python scrapers for each supported exchange.
- `ki_binance_scanner.py`: The highest-weight feed (0.16).
- `ki_indodax_scanner.py`: The base reference feed (0.10).
- `ki_whale_scanner.py`: Tracking large movements on-chain.

### 2. [Deployment](file:///Users/kiki/Documents/Web%20Develop/KiBot/SCANNER/Deployment/)
Systemd unit files for running the scanners as persistent background services on Linux nodes.

### 3. [Auth](file:///Users/kiki/Documents/Web%20Develop/KiBot/SCANNER/Auth/)
Secure SSH keys for remote scanner nodes.

## Audit Observation: Latency Sensitivity
The `SIGNAL_WINDOW_S` is set to 5 seconds. This is a tight window. Any network lag between the scanner nodes and the central manager will result in missed entries. The "Urgent Scout" feature added recently helps mitigate this by providing a secondary validation path when signals are borderline.
