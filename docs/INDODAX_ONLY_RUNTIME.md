# KiBot Indodax-Only Runtime

KiBot now runs with a single executable venue: Indodax.

## Why Phantom/Web3 Is Retired

The operator marked the Phantom wallet as compromised/useless. KiBot must not
read Phantom private keys, query Solana RPCs for trading, build Jupiter swaps,
or count Phantom balances in live PnL.

Canonical runtime flags:

```env
KIBOT_INDODAX_ONLY=true
KIBOT_PHANTOM_ENABLED=false
KIBOT_ENABLE_REAL_SWAP=false
KIBOT_ENABLE_REAL_BRIDGE=false
KIBOT_ENABLE_REAL_WITHDRAWAL=false
KIBOT_WITHDRAWAL_ENABLED=false
KIBOT_ENABLE_POLYMARKET_LIVE=false
KIBOT_SCANNER_ENABLE_WEB3=false
KIBOT_SCANNER_ENABLE_POLYMARKET=false
```

## Money Truth

Total equity is:

```text
Indodax IDR cash
+ Indodax held coin mark-to-market value
+ pending Indodax BUY reserve
```

Retired Phantom/Web3 balances are excluded from:

- total equity
- daily PnL
- daily loss cap
- route readiness
- dashboard venue allowances

## Realistic Indodax Strategy Contract

The system should only enter when an Indodax setup remains profitable after
all operational costs:

- minimum Indodax Pro order: Rp25.000
- fee/tax/CFX all-in fee must be included
- entry must use current ask/depth, not stale last price
- exit must be sellable using bid/depth before buy
- stale limit orders must be cancelled or repriced
- Binance lead-lag is confirmation only, never a standalone buy trigger
- empty lead-lag opportunities mean no edge, not a service outage

## Runtime Verification

Use:

```bash
PYTHONPATH=. python3 scripts/retire_phantom_runtime.py
PYTHONPATH=. python3 scripts/assert_indodax_only_runtime.py
PYTHONPATH=. python3 scripts/assert_live_truth_writer.py
PYTHONPATH=. python3 scripts/healthcheck.py
```

Server deployment must also disable these retired systemd units:

```text
kibot-phantom-brain
kibot-pumpfun
kibot-base
kibot-future-web3
kibot-web3-exit
kibot-executor-polymarket
```
