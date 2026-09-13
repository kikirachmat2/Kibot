# Live Control Architecture

## Runtime
KiBot currently operates as an Indodax-only autonomous runtime.

## Gates
- Runtime gate
- Wallet/accounting reconciliation
- Expected value hard gate
- Pre-trade simulator hard gate
- Risk gate
- Pair memory/quarantine
- Order timeout/cancel

## Dashboard Truth
The dashboard must treat `state/live_truth.json` as canonical money truth. Legacy debug state may be shown only as secondary diagnostic context.

## Telegram
Telegram is reserved for important exceptions, restarts/recoveries, daily summaries, and real trade summaries.
