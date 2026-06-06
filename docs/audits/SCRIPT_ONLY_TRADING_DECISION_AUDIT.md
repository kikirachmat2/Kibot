# Script-Only Trading Decision Audit

Current scope: Indodax-only.

## Decision Path
1. Indodax scanner produces candidates.
2. Council/advisory layer can critique and rank, but cannot bypass deterministic gates.
3. Expected value, pre-trade simulation, risk gate, and balance reconciliation must pass before order submission.
4. Executor records every pending/fill/exit event in order state, trade history, and decision journal.

## Removed Scope
External wallet/chain/prediction-market route scanners and executors are no longer part of the live decision path.
