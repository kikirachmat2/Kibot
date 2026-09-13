# Final Autonomy Runtime Audit

## Current Scope
KiBot autonomy currently controls Indodax-only runtime.

## Runtime Truth
- Money truth must come from `state/live_truth.json`.
- Trade lifecycle must be logged in order state, trade history, and decision journal.
- AI/advisory layers can diagnose and critique but cannot approve or bypass deterministic gates.

## Removed Scope
External wallet, chain, and prediction-market runtime paths are not active.
