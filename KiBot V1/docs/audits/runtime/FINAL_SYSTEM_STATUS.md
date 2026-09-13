# Final System Status

Current architecture: Indodax-only live runtime with deterministic gates.

## Active Venue
- Indodax spot.

## Retired Runtime
External wallet/chain/prediction-market execution routes are removed from the current runtime contract.

## Required Truth
- `state/live_truth.json` must be fresh.
- Dashboard PnL must follow live truth.
- Executor must write order/trade lifecycle logs.
