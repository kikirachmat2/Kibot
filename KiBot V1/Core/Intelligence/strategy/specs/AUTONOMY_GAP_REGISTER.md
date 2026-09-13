# KiBot Autonomy Gap Register

## Current Baseline
| Area | Runtime Maturity | Status |
|---|---:|---|
| Indodax trading runtime | 80-88% | Scanner/Council/RiskGate/Executor active; calibration continues |
| Accounting truth | 80-90% | Live truth active; dashboard must not use legacy money state |
| System autonomy | 72-82% | System Commander and AI scout active |
| Dashboard observability | 78-88% | Live truth and action panels wired |
| Backup/restore | 70-80% | Backup scripts exist; restore drills still needed |
| Provider/source routing | 70-82% | Health/cooldown states exist; calibration continues |

## Priority Gaps
### G-001 — Accounting Drift
- Ensure all money panels read the same live truth.

### G-002 — Stale Order Handling
- Pending orders must cancel or reprice when market moves away.

### G-003 — Pair Memory
- Repeated loser pairs must be penalized or quarantined.

### G-004 — Learning Warehouse
- Rejected and missed candidates need enough outcome data to tune thresholds.

### G-005 — Server Self-Healing
- Patrol should repair known service/state issues before notifying the operator.

## Closure Rule
A gap is closed only when code, state output, dashboard/report visibility, docs, and smoke tests all agree.
