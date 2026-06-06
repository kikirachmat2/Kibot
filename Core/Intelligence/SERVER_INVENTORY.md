# KiBot Intelligence Server Inventory

This file mirrors the current operator contract for AI/council/runtime tooling.

## Active Runtime
- Venue: Indodax spot.
- Source of truth: `state/live_truth.json`.
- Operator command: `bin/kibotctl`.
- Service source of truth: `systemd`.

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

## AI Usage
- AI can patrol logs, summarize risk, review strategy, and explain runtime incidents.
- AI cannot approve trades, bypass EV, bypass pre-trade simulation, increase size, or override loss locks.

## Removed Runtime
External wallet/chain/prediction-market route code and services are not part of the current runtime contract.
