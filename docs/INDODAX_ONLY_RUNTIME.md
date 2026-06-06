# KiBot Indodax-Only Runtime

KiBot now has one executable venue: Indodax.

## Runtime Contract

Canonical runtime flags:

```env
KIBOT_INDODAX_ONLY=true
KIBOT_WITHDRAWAL_ENABLED=false
KIBOT_SCANNER_ENABLE_UNIVERSAL=false
```

The runtime must not load non-Indodax wallet keys, route scanners, route
executors, or route accounting files.

## Money Truth

Total equity is:

```text
Indodax IDR cash
+ Indodax held coin mark-to-market value
+ pending Indodax BUY reserve
```

This same total is used by:

- dashboard portfolio card
- daily PnL
- daily loss cap
- capital governor
- accounting truth
- live truth

## Realistic Indodax Strategy Contract

The system should only enter when an Indodax setup remains profitable after all
operational costs:

- minimum Indodax Pro order must be met
- fee, spread, and slippage must be included
- entry must use current ask/depth, not stale last price
- exit must be sellable using bid/depth before buy
- stale limit orders must be cancelled or repriced
- Binance lead-lag is confirmation only, never a standalone buy trigger
- empty lead-lag opportunities mean no edge, not a service outage

## Runtime Verification

Use:

```bash
PYTHONPATH=. python3 scripts/assert_indodax_only_runtime.py
PYTHONPATH=. python3 scripts/assert_live_truth_writer.py
PYTHONPATH=. python3 scripts/healthcheck.py
```

Server deployment must keep only the canonical Indodax runtime services active.
