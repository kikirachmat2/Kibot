# KiBot Sovereign Shield (Security)
================================

This directory contains the autonomous security infrastructure of KiBot, designed to protect capital, ensure trade integrity, and safeguard credentials.

## Components

### 1. Trade Sentinel (`kibot_sentinel.py`)
The **Trade Sentinel** is the real-time guardian of the order flow. It acts as a mandatory VETO gate for every trade request.
- **Velocity Control**: Monitors transaction frequency and cumulative losses per minute.
- **Anomaly Detection**: Vetoes orders with significant price deviations (>5%) from the market mid-price (fat-finger protection).
- **Killswitch Logic**: Automatically halts trading if safety thresholds are breached.

### 2. Immutable Logging (`kibot_security.py`)
Provides a cryptographically verifiable audit trail of all security events.
- **HMAC-SHA256 Signing**: Every log entry is signed with a hardware-bound key.
- **Integrity Verification**: Detects unauthorized log tampering or deletions.
- **Periodic Scanning**: Monitors sensitive file permissions (e.g., `.env` access).

## Usage

### Verifying Log Integrity
To check if logs have been tampered with:
```bash
python3 Security/kibot_security.py --verify
```

### Security Log
All audited events are stored in `state/security_log.jsonl` in a signed JSON format.

## Security Policy
1. **Fail-Closed**: If the security vault is inaccessible, the system will refuse to boot.
2. **Sovereign Egress**: All trading communication must pass through verified sovereign network paths.
3. **Hardware Bound**: Security keys are derived from the server's unique hardware footprint, preventing unauthorized credential reuse.
