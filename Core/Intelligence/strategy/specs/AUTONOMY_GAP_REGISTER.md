# KiBot Sovereign — Autonomy Gap Register

> Purpose: single register of what still prevents KiBot from being a fully
> autonomous system. This file translates strategy into named gaps that can be
> implemented, tested, and closed.

---

## Current Baseline

These numbers are runtime implementation maturity, not profit guarantees and
not a replacement for deploy smoke tests. The register must stay honest so the
dashboard and operator do not mistake documentation completeness for live
runtime proof.

| Area | Runtime Maturity | Status |
|---|---:|---|
| Trading runtime | 80-88% | Scanner/Council/RiskGate/Executor active; remaining work is calibration from outcomes |
| System autonomy | 72-82% | System Commander active; recovery policy exists; operator-required failures still surfaced |
| Inventory utilization | 75-85% | Runtime matrix active; every inventory item is now visible/scored where possible |
| Polymarket runtime | 55-70% | Wallet/API baseline and event intelligence exist; full probability/position lifecycle still maturing |
| Dashboard observability | 78-88% | System Brain, Council Lens, source health, drift, and inventory panels wired |
| Backup/restore | 70-80% | Backup/pre-deploy scripts exist; restore drills and off-server backup still future work |
| Provider/source routing | 70-82% | Health/cooldown states exist; provider calibration still needs production outcome data |

---

## Runtime Alignment Sign-off

**Date:** 2026-05-15
**Auditor:** Codex / KiBot Sovereign Agent
**Verdict:** CORE AUTONOMY FOUNDATION ACTIVE, CONTINUOUS VERIFICATION REQUIRED.
**Notes:** G-001 to G-008 now have code-level implementations and dashboard/state
surfaces. The deploy rule remains strict: after every material change, run
syntax checks, dashboard summary checks, service checks, and server drift checks
before trusting live operation.

---

## Priority Gaps

### G-001 — System Commander Missing [RESOLVED]

- Status: IMPLEMENTED in `system_commander.py`.
- Features: health, recovery, drift, config validation.

### G-002 — Inventory Is Not Runtime-Aware [RESOLVED]

- Status: IMPLEMENTED in `system_commander.py` and Dashboard.
- Features: matrix analysis of `SERVER_INVENTORY.md`.

### G-003 — Polymarket Intelligence Incomplete [PARTIAL-RUNTIME]

- Status: IMPLEMENTED foundation in `polymarket_intelligence.py` and integrated into `SovereignCouncil`.
- Features: edge scoring, liquidity simulation, and resolution risk vetting.
- Runtime note: event-market vetoes must apply to Polymarket/event markets only,
  not Indodax pump signals.

### G-004 — Provider/Source Health Not Fully Scored [RESOLVED]

- Status: IMPLEMENTED in `kibot_ai_search.py` and `kibot_ai_coordinator.py`.
- Features: latency/success tracking, persistent health state.

### G-005 — No Full Backup/Restore Automation [IMPLEMENTED-NEEDS-DRILL]

- Status: IMPLEMENTED in `bin/kibot-backup.sh`.
- Features: state/config archiving and rotation.
- Runtime note: restore drills and off-server copy are still required before this
  can be called disaster-proof.

### G-006 — No Deployment Guard [RESOLVED]

- Status: IMPLEMENTED in `bin/kibot-pre-deploy.sh`.
- Features: drift detection, safety validation, pre-flight checks.

### G-007 — Dashboard Does Not Show Whole System Brain [RESOLVED]

- Status: IMPLEMENTED in `index.html`, `style.css`, `live.js`.
- Features: System Brain banner, Inventory bars, Source Health dots.

### G-008 — Learning Warehouse Not Complete [IMPLEMENTED-FOUNDATION]

- Status: IMPLEMENTED in `decision_journal.py`.
- Features: tracking rejected candidates and missed opportunities.
- Runtime note: strategy calibration still depends on enough clean production
  samples and post-decision outcome windows.

---

## Closure Rule

A gap is closed only when:

- code exists,
- state output exists,
- dashboard or report exposes it,
- docs/inventory mention it,
- smoke test verifies it.
