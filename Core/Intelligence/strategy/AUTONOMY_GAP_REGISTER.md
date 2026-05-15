# KiBot Sovereign — Autonomy Gap Register

> Purpose: single register of what still prevents KiBot from being a fully
> autonomous system. This file translates strategy into named gaps that can be
> implemented, tested, and closed.

---

## Current Baseline

| Area | Runtime Maturity | Main Gap |
|---|---:|---|
| Trading runtime | 60-70% | Not all `TRADING_STRATEGY.md` contracts are enforced in code |
| System autonomy | 45-55% | No central System Commander yet |
| Inventory utilization | 55-65% | Inventory is documented but not fully machine-used |
| Polymarket runtime | 35-50% | Event probability/resolution/liquidity stack incomplete |
| Dashboard observability | 65-75% | Missing system-brain panels |
| Backup/restore | 25-40% | No full state backup/restore automation |
| Provider/source routing | 50-65% | Health and role suitability are partial |

---

## Priority Gaps

### G-001 — System Commander Missing

Problem:

- `kibot-janitor` exists, but no single non-trading brain owns health,
  recovery, drift, config validation, and backup decisions.

Required closure:

- implement System Commander module,
- emit `state/system_commander.json`,
- feed dashboard,
- degrade trading when system is blind/unsafe.

### G-002 — Inventory Is Not Runtime-Aware

Problem:

- `SERVER_INVENTORY.md` lists services, models, APIs, and tools, but runtime does
  not actively score usage/health for each item.

Required closure:

- implement inventory utilization matrix,
- track installed/active/used/healthy/last_checked,
- show unused or broken inventory on dashboard.

### G-003 — Polymarket Intelligence Incomplete

Problem:

- Polymarket executor exists, but event-specific intelligence is not as mature
  as Indodax pump intelligence.

Required closure:

- probability engine,
- resolution parser,
- liquidity simulator,
- evidence bundle,
- expiry/rule ambiguity scorer,
- mark-to-market and position reconciliation.

### G-004 — Provider/Source Health Not Fully Scored

Problem:

- Many AI/search providers exist, but role routing and quality scoring are not
  fully systematic.

Required closure:

- provider capability matrix,
- source health matrix,
- latency/failure/cooldown tracking,
- dashboard panel for provider/source health.

### G-005 — No Full Backup/Restore Automation

Problem:

- Critical state is known, but automated backup/restore and verification are
  incomplete.

Required closure:

- state backup script,
- restore checklist script,
- backup status dashboard,
- optional off-server sync.

### G-006 — No Deployment Guard

Problem:

- Deploy currently depends on agent discipline.

Required closure:

- pre-deploy checks,
- changed-file classification,
- compile/smoke checks,
- service restart plan,
- rollback hints.

### G-007 — Dashboard Does Not Show Whole System Brain

Problem:

- Dashboard shows trading flow, but not full inventory, drift, backups,
  provider/source health, and system commander state.

Required closure:

- dashboard system-brain panel,
- inventory usage panel,
- source health panel,
- drift panel,
- backup panel.

### G-008 — Learning Warehouse Not Complete

Problem:

- decision journal exists, but rejected candidates, missed pumps, incidents, and
  system events are not fully structured into a queryable warehouse.

Required closure:

- candidate outcome windows,
- missed opportunity table,
- incident records,
- role accuracy stats,
- executor quality stats.

---

## Closure Rule

A gap is closed only when:

- code exists,
- state output exists,
- dashboard or report exposes it,
- docs/inventory mention it,
- smoke test verifies it.

