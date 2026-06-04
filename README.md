# KiBot

**Agentic trading automation, runtime orchestration, and safety-first autonomous agent infrastructure.**

KiBot is an experimental open-source framework for building and operating autonomous market agents with explicit safety gates, audit trails, runtime observability, and human-readable control surfaces. The project combines market scanners, AI-assisted decisioning, risk-aware execution, security hardening, and operational tooling into one repository.

> **Status:** Active development / early runtime.  
> **Important:** KiBot is experimental software. It is not financial advice and should not be treated as a guaranteed profit system. Real-money execution is intentionally blocked unless an operator explicitly enables the live trading gate.

---

## Why KiBot exists

Autonomous agents are powerful, but high-stakes automation needs more than a script that reacts to signals. KiBot is built around the idea that autonomous systems should be inspectable, bounded, and recoverable.

The project focuses on:

- **Council-gated decisioning**: raw scanner signals are treated as evidence, not direct orders.
- **Explicit live trading gates**: real-money orders require `KIBOT_LIVE_TRADING_ENABLED=true` or `KIBOT_TRADING_MODE=live`.
- **Risk-aware execution**: entries pass through pre-trade simulation, orderbook checks, fee-aware sizing, and RiskGate validation.
- **Runtime observability**: dashboards, state snapshots, decision journals, and daily reports make the system easier to inspect.
- **Security-first operations**: HMAC-signed signals, encrypted secret loading, audit logs, throttled notifications, and fail-closed behavior are treated as core infrastructure.
- **Honest autonomy tracking**: strategy documents separate design intent from runtime maturity so the system does not overstate its readiness.

---

## Core capabilities

### Market scanning

KiBot includes scanner modules for Indodax, Polymarket, and cross-source lead-lag context. Scanner output is deduplicated, structured, and routed as evidence for downstream decisioning.

Highlights include:

- Indodax small-cap pump and continuation detection.
- Binance-to-Indodax lead-lag monitoring.
- Polymarket opportunity scanning.
- Universal lead-lag context signals.
- Anti tick-trap filtering for low-quality pump setups.

### AI-assisted decisioning

The intelligence layer aggregates portfolio state, market data, historical decisions, what-if simulation, and external evidence. KiBot uses bounded AI deliberation with deterministic fallbacks so slow or unavailable providers do not freeze the runtime.

Key components include:

- `SovereignCouncil` for structured decision flow.
- `kibot_ai_scout.py` for market scouting and runtime patrol.
- `kibot_whatif_engine.py` for scenario simulation.
- `probability_engine.py` for deadline-aware green-state probability.
- `decision_journal.py` for auditable scanner, council, simulation, and executor events.

### Execution and risk controls

Executors only act on validated mandates unless an explicit debug override is enabled. The execution path is designed to prevent raw scanner output from bypassing council, simulation, and risk checks.

Safety mechanisms include:

- Explicit live trading gate.
- Pre-trade orderbook simulation.
- Spread, slippage, sellable-minimum, and partial-take-profit feasibility checks.
- Fee-aware exit planning.
- Wallet/open-order reconciliation.
- Daily PnL mark-to-market accounting.
- Hard-loss and exit-only runtime states.

### Security and operations

KiBot treats autonomous trading infrastructure as sensitive infrastructure.

Security and operational controls include:

- HMAC-SHA256 signal signing.
- Hardware-bound encrypted vault loading through KiVault.
- Fail-closed secret handling.
- Signed security audit logs.
- Telegram throttle and dedupe controls.
- `systemd` service contracts for runtime components.
- `bin/kibotctl` as the main operator wrapper for status, doctor checks, restarts, model sync, and dashboard launch.

### Visual control plane

The project includes a dashboard/control-plane layer for viewing runtime state, delegation flow, activity logs, live ledgers, strategy state, and agent/workflow status.

Primary dashboard entrypoints:

- `Core/Intelligence/kibot_dashboard.py`
- `Core/Intelligence/dashboard/`
- `bin/kibot-dashboard`
- `config/systemd/kibot-dashboard.service`

---

## Repository map

| Path | Purpose |
| --- | --- |
| [`Core/README.md`](./Core/README.md) | Core architecture and runtime overview. |
| [`Core/Scanner/README.md`](./Core/Scanner/README.md) | Scanner flow, delta filtering, and market signal routing. |
| [`Core/Executors/README.md`](./Core/Executors/README.md) | Execution layer, capital routing, and risk checks. |
| [`Core/Intelligence/README.md`](./Core/Intelligence/README.md) | AI orchestration, aggregator, learning loop, what-if simulation, and dashboards. |
| [`Core/Security/README.md`](./Core/Security/README.md) | HMAC, vault, audit logging, and security posture. |
| [`Core/Support/README.md`](./Core/Support/README.md) | Config, utilities, operational helpers, and system support tooling. |
| [`Core/Decision/daily_reset_coordinator.py`](./Core/Decision/daily_reset_coordinator.py) | WIB daily rollover and baseline reset coordinator. |
| [`Core/Intelligence/strategy/TRADING_STRATEGY.md`](./Core/Intelligence/strategy/TRADING_STRATEGY.md) | Trading strategy contract and runtime behavior. |
| [`Core/Intelligence/strategy/SYSTEM_STRATEGY.md`](./Core/Intelligence/strategy/SYSTEM_STRATEGY.md) | Non-trading system strategy for health, recovery, deployment, and automation. |
| [`Core/Intelligence/strategy/specs/AUTONOMY_GAP_REGISTER.md`](./Core/Intelligence/strategy/specs/AUTONOMY_GAP_REGISTER.md) | Known autonomy gaps before claiming stronger runtime maturity. |
| [`Core/Intelligence/strategy/roadmaps/IMPLEMENTATION_ROADMAP.md`](./Core/Intelligence/strategy/roadmaps/IMPLEMENTATION_ROADMAP.md) | Implementation roadmap from strategy to runtime. |
| [`Core/Intelligence/strategy/specs/OBSERVABILITY_DASHBOARD_SPEC.md`](./Core/Intelligence/strategy/specs/OBSERVABILITY_DASHBOARD_SPEC.md) | Dashboard and control-plane specification. |
| [`Core/Intelligence/delegation_workflows.md`](./Core/Intelligence/delegation_workflows.md) | Human-readable delegation workflow playbook. |
| [`Core/Intelligence/delegation_workflows.json`](./Core/Intelligence/delegation_workflows.json) | Machine-readable delegation workflow manifest. |
| [`bin/kibotctl`](./bin/kibotctl) | One-command operational wrapper. |
| [`bin/kibot-dashboard`](./bin/kibot-dashboard) | Dashboard launcher. |
| [`config/systemd/`](./config/systemd) | Canonical systemd service definitions. |
| [`AGENTS.md`](./AGENTS.md) | Instructions for Codex, Aider, Copilot, and repository automation. |
| [`state/`](./state) | Runtime JSON snapshots used by the engine. Do not commit secrets. |

---

## Typical runtime flow

```text
Market data / external evidence
        ↓
Scanner evidence bundle
        ↓
Council deliberation + what-if simulation
        ↓
Pre-trade orderbook simulation
        ↓
RiskGate / capital governor
        ↓
Executor
        ↓
Decision journal + dashboard + Telegram incident channel
```

Real-money execution is not the default path. The runtime must pass the explicit live gate and the relevant risk checks before any live order is allowed.

---

## Operating principles

- Treat `systemd` as the source of truth for runtime services.
- Use `bin/kibotctl` for status checks, doctor checks, restarts, model sync, and dashboard operations.
- Do not introduce duplicate daemons when canonical services already exist.
- Keep README, inventory, and strategy docs updated when server state or runtime behavior changes.
- Never commit secrets, `.env` files, decrypted vault material, private keys, or exchange credentials.
- Prefer sparse, deduplicated notifications over noisy alert loops.
- Treat healthchecks as read-only by default. Emergency rollback/KILL_SWITCH creation requires
  `KIBOT_HEALTHCHECK_ALLOW_ROLLBACK=true`; otherwise use assertions such as
  `scripts/assert_anchor_contract.py` to report runtime drift without mutating production.
- Document any change that affects live trading, Telegram behavior, or server health.

---

## Safety disclaimer

KiBot is a research and engineering project for autonomous agent infrastructure. It can interact with financial systems when configured by an operator, but it is not a recommendation engine, investment advisor, or guarantee of returns. Use paper trading, test environments, code review, and strict risk controls before considering any live deployment.

---

## Project motto

> Sedikit demi sedikit, lama-lama menjadi bukit.

Small improvements compound into stronger systems.
