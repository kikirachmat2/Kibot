# KiBot System Strategy

## Current Mission
Run a focused Indodax-only autonomous trading system that protects accounting truth, avoids overtrade, and only enters when deterministic gates pass.

## Runtime Principles
- Source of truth is `state/live_truth.json`.
- `systemd` is source of truth for services.
- `bin/kibotctl` is the operator entrypoint.
- AI is advisory and diagnostic only.
- Telegram is exception-only plus important trade summaries.

## Active Services
- `kibot-master`
- `kibot-scanner`
- `kibot-executor`
- `kibot-live-truth`
- `kibot-capital-governor`
- `kibot-ai-scout`
- `kibot-dashboard`
- `ollama`
- `redis-server`

## Trading Contract
- Venue: Indodax spot.
- Entry requires scanner evidence, EV approval, pre-trade simulation pass, risk gate pass, available balance, and valid exit plan.
- Exit must be fee-aware and reconciled against wallet/order state.
- Pair memory and loss quarantine should prevent repeating obvious losers.

## Removed Runtime
External wallet, chain, and prediction-market systems are not part of the current strategy.
