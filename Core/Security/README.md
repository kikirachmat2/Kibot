# KiBot Security (Sovereign Shield)

Repository-wide security infrastructure for the sovereign trading cluster.

## Ringkas
- HMAC dipakai untuk payload UDP dan state integrity.
- Vault dipakai untuk secret loading saat boot.
- Log audit disimpan terpisah agar mudah ditinjau dan diverifikasi.
- HTTP client logging dijaga di level error supaya query string berisi API key tidak bocor ke journal.

## Paranoid Security Posture (v8.2)

The system operates under a "Paranoid Reconstruction" model, assuming the network environment and persistent storage are potentially compromised.

### 1. Inter-Node HMAC Trust
All signals transmitted over UDP (breakout detections, lead-lag signals) are cryptographically signed using **HMAC-SHA256**.
- **Emitter**: `SignalUdpEmitter.kt` signs the JSON payload before transmission.
- **Receiver**: `kibot_manager.py` verifies the signature using a hardware-bound key (`KIBOT_SIGNAL_KEY`).
- **Bi-directional ACK**: The receiver sends a verified ACK back to the emitter to confirm receipt of a trusted signal.

### 2. Sovereign Vault (KiVault)
We have migrated from plaintext `.env` files to encrypted `.env.kiv` containers.
- **Root of Trust**: Encryption keys are derived from hardware-unique identifiers (MAC + CPU Node).
- **In-Memory Decryption**: Secrets are decrypted directly into `os.environ` at runtime, ensuring no plaintext API keys are ever written to disk in a readable format.
- **CLI Usage**: `python3 ki_vault.py setup` to encrypt local `.env` and `python3 ki_vault.py load` to verify.

### 3. Intelligence Sanitization
To prevent "Adversarial Data Poisoning", the intelligence layer implements strict input validation:
- **PnL Clipping**: Bayesian updates are capped at `[-20%, +50%]` to prevent extreme outlier data from corrupting the AI's risk models.
- **Signal TTL**: Signals older than 10-15 seconds are automatically rejected to prevent replay attacks or execution on stale market conditions.
- **Live Trading Gate**: real-money entry is blocked unless the operator explicitly enables `KIBOT_LIVE_TRADING_ENABLED` or `KIBOT_TRADING_MODE=live`.

## Hardening Checklist
- [x] Oracle Circuit Breaker (Veto price jumps > 2%)
- [x] HMAC State Integrity (Sign `learning_state.json`)
- [x] Inter-Node HMAC (Sign UDP signals)
- [x] Hardware-bound KiVault (AES-256)
- [x] Humility-weighted Sizing (Cap Kelly at 0.95)
- [x] Telegram Throttle / Dedupe (Shared channel guardrail)
- [ ] Final Secret Purge (Remove legacy .env files)

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
4. **Sparse Notifications**: Telegram is an incident channel, not a chat log.
