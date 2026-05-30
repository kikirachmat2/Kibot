# Phantom Live Setup

This document explains how to prepare Phantom/Solana runtime without exposing secrets in the repository.

## Required environment variables

Set these in the Batam `.env` or secure secret manager:

- `KIBOT_PHANTOM_ENABLED=true`
- `PHANTOM_PRIVATE_KEY=<base58 encoded secret key>`
- `SOLANA_RPC_URL=<solana rpc endpoint>`
- `KIBOT_SOLANA_RPC_URL=<optional alternate rpc endpoint>`
- `KIBOT_PHANTOM_MAX_POSITION_SOL=0.05`
- `KIBOT_PHANTOM_MAX_PRICE_IMPACT_PCT=1.0`
- `KIBOT_PHANTOM_MAX_SLIPPAGE_BPS=100`
- `KIBOT_ALLOW_ASSERTION_MICRO_SWAP=false`

## Safety rules

- Do not commit private keys, seed phrases, API tokens, or RPC secrets.
- Keep bridge disabled.
- Keep withdrawal disabled.
- Do not run a real Phantom swap unless the operator explicitly sets `KIBOT_ALLOW_ASSERTION_MICRO_SWAP=true` for a controlled assertion only.

## What the runtime checks

The Phantom runtime diagnosis checks:

- env presence
- signer derivation
- RPC health
- Jupiter quote health
- Jupiter swap-build health
- wallet reconciliation path

If any required env is missing, the safe result is:

- `OK:PHANTOM_LOCKED_MISSING_ENV`

If env exists but signing fails, the safe result is:

- `BLOCKED_BY_PHANTOM_SIGNING`

If RPC fails, the safe result is:

- `BLOCKED_BY_RPC`

If Jupiter quote/build fails, the safe result is:

- `BLOCKED_BY_JUPITER`

If everything passes, the safe result is:

- `OK:PHANTOM_LIVE_READY`

## Deployment note

After updating secrets on Batam, restart the live-truth writer and re-run:

```bash
PYTHONPATH=. .venv/bin/python scripts/diagnose_phantom_runtime.py
PYTHONPATH=. .venv/bin/python scripts/assert_phantom_live_ready.py
PYTHONPATH=. .venv/bin/python scripts/assert_phantom_runtime_autonomy.py
```
