# KiBot Sovereign — Implementation Roadmap

> Purpose: phased execution plan for turning `TRADING_STRATEGY.md` and
> `SYSTEM_STRATEGY.md` into runtime behavior.

---

## Phase 0 — Documentation Sync

Goal: make the repo and server agree on the new strategy file layout.

Tasks:

- replace references to `PUMP_LIFECYCLE_STRATEGY.md` with `TRADING_STRATEGY.md`,
- deploy `TRADING_STRATEGY.md` and `SYSTEM_STRATEGY.md` to Batam,
- update README and server inventory,
- remove stale doc references from dashboards/tooling.

Exit criteria:

- local GitHub and Batam server reference the same canonical strategy docs.

---

## Phase 1 — System Commander Foundation

Goal: build the missing non-trading control brain.

Tasks:

- create `Core/Support/system_commander.py`,
- classify system state as `HEALTHY`, `DEGRADED`, `RECOVERING`, `BLIND`,
  `UNSAFE`,
- read service status, disk/RAM, model health, source health, drift status,
- write `state/system_commander.json`,
- expose summary to dashboard.

Exit criteria:

- dashboard can say why system is healthy/degraded/blind.

---

## Phase 2 — Inventory Utilization Runtime

Goal: make server inventory machine-readable and actionable.

Tasks:

- create inventory utilization builder,
- map services, models, APIs, tools, and state files,
- compute utilization score,
- identify installed-but-unused and referenced-but-missing items,
- show inventory health on dashboard.

Exit criteria:

- every major inventory item has health, owner, and usage status.

---

## Phase 3 — RiskGate V4

Goal: make RiskGate the adaptive risk brain.

Tasks:

- normalize top-level and nested spread,
- read `daily_context`,
- read `fallback_category`,
- read `trade_grade`,
- read `exit_quality`,
- read `pre_trade_simulation`,
- use starting equity for drawdown,
- output approved budget/sizing recommendation.

Exit criteria:

- executor uses RiskGate sizing output rather than duplicating budget logic.

---

## Phase 4 — Polymarket Runtime V2

Goal: raise Polymarket from basic executor to event intelligence system.

Tasks:

- probability engine,
- resolution parser,
- liquidity simulator,
- evidence bundle,
- expiry risk scorer,
- mark-to-market position tracker,
- Polymarket role votes in council.

Exit criteria:

- Polymarket BUY mandate cannot execute without probability, liquidity,
  resolution, and evidence fields.

---

## Phase 5 — Data Warehouse and Learning Loop

Goal: learn from executed, rejected, and missed decisions.

Tasks:

- store candidate snapshots,
- store rejected candidates,
- store missed pump outcomes,
- track post-decision windows,
- track role accuracy,
- track execution quality.

Exit criteria:

- dashboard can answer: “why did KiBot not buy this pump, and was that correct?”

---

## Phase 6 — Dashboard V4

Goal: show the system brain, not only trading cards.

Tasks:

- Capital Commander panel,
- RiskGate reason panel,
- rejected/missed candidates,
- provider/source health,
- model routing,
- server drift,
- backup status,
- System Commander state,
- Telegram report preview.

Exit criteria:

- operator can see trading, system, and intelligence health from one screen.

---

## Phase 7 — Backup, Restore, Deployment Guard

Goal: make system changes safer.

Tasks:

- state backup script,
- restore verification,
- config validator,
- deployment guard,
- rollback notes,
- drift detector.

Exit criteria:

- live-critical deploys run a repeatable pre/post checklist.

---

## Phase 8 — Mobile/API Bridge

Goal: make APK a cockpit, not a second brain.

Tasks:

- endpoint config,
- version display,
- dashboard/API health,
- read-only diagnostics,
- no duplicated trading logic,
- no secrets in app.

Exit criteria:

- mobile can show health and account state without bypassing core runtime.

