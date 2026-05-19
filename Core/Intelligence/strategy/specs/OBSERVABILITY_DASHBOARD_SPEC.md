# KiBot Sovereign — Observability and Dashboard Spec

> Purpose: define the dashboard/control-plane information architecture needed
> for full system visibility.

---

## Dashboard Mission

The dashboard must answer:

- is KiBot alive?
- is KiBot safe to trade?
- what does KiBot know?
- what is stale?
- what did KiBot do?
- what did KiBot reject?
- what needs operator help?

---

## Required Panels

### 1. Sovereign Header

- combined equity,
- daily GREEN state,
- deadline clock,
- system state,
- trading allowed/blocked.

### 2. Delegation Graph

- operator,
- council,
- scanner,
- AI brain,
- Indodax executor,
- Polymarket executor,
- verifier,
- janitor/system commander.

### 3. Capital Commander

- current capital mode,
- preferred exchange,
- cash reserve,
- allowed budget,
- green lock status.

### 4. RiskGate Panel

- last pass/reject,
- reason,
- trade grade,
- category,
- unit-price rule,
- daily drawdown state.

### 5. Candidate Intelligence

- top candidates,
- rejected candidates,
- missed pumps,
- wait reasons,
- what would change decision.

### 6. Polymarket Event Panel

- market id,
- question,
- price,
- estimated probability,
- edge,
- resolution risk,
- liquidity score,
- expiry risk.

### 7. Source and Provider Health

- AI provider cooldowns,
- web/search source health,
- API reachability,
- stale evidence warnings.

### 8. Inventory Utilization

- services,
- models,
- tools,
- APIs,
- state files,
- unused/missing/broken items.

### 9. GitHub / Server Drift

- local HEAD,
- origin HEAD,
- dirty files,
- dangerous drift flag.

### 10. Backup / Restore

- last backup,
- protected state status,
- restore readiness.

### 11. Event Trail

- trading events,
- system events,
- recovery events,
- errors,
- Telegram alerts.

---

## Design Rule

Dashboard may be dense. Telegram must stay sparse.

```text
Dashboard = full observability.
Telegram = only daily intelligence and unrecovered danger.
```

