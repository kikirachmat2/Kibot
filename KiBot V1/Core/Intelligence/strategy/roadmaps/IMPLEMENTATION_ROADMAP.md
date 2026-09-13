# KiBot Implementation Roadmap

## Phase 0 — Runtime Scope Lock
Status: DONE.

- Runtime scope is Indodax-only.
- External wallet/chain/prediction-market routes are retired.
- README, inventory, dashboard, and strategy docs must stay aligned with that scope.

## Phase 1 — Accounting Truth
Status: ACTIVE.

- `state/live_truth.json` is the canonical money source.
- Dashboard and council must use total Indodax equity, not partial cash-only views.
- PnL must separate realized, unrealized, fees, and dust.

## Phase 2 — Indodax Execution Quality
Status: ACTIVE.

- Pre-trade simulation before buy.
- Fee-aware exit plan before entry.
- Stale order cancel.
- Pair memory/quarantine.
- Trade history reconciliation.

## Phase 3 — Learning Loop
Status: FOUNDATION ACTIVE.

- Store accepted, rejected, and missed candidates.
- Measure post-decision outcomes.
- Penalize repeated loser pairs.
- Use evidence to tune thresholds without letting AI bypass gates.

## Phase 4 — Dashboard Clarity
Status: ACTIVE.

- Show live truth freshness.
- Show total equity, realized/unrealized PnL, fees, open orders, and blocked reason.
- Hide legacy panels.

## Phase 5 — Server Autonomy
Status: ACTIVE.

- Keep `systemd` as runtime source of truth.
- Use `bin/kibotctl` for operator checks.
- Patrol logs and services every cycle.
- Notify Telegram only for important exceptions and trade summaries.
