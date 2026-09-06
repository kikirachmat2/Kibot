# KiBot

**Agentic trading automation, runtime orchestration, and safety-first autonomous agent infrastructure.**

KiBot is an experimental open-source framework for building and operating autonomous market agents with explicit safety gates, audit trails, runtime observability, and human-readable control surfaces. The project combines market scanners, AI-assisted decisioning, risk-aware execution, security hardening, and operational tooling into one repository.

> **Status:** Active development / early runtime.  
> **Important:** KiBot is experimental software. It is not financial advice and should not be treated as a guaranteed profit system. Real-money execution is intentionally blocked unless an operator explicitly enables the live trading gate.

---

## Current Operator Runtime

KiBot is currently configured as **Indodax-only**.

- Canonical executable venue: Indodax.
- Runtime flag: `KIBOT_INDODAX_ONLY=true`.
- Non-Indodax wallet, chain, and prediction-market routes have been removed from the runtime.
- Dashboard and PnL truth are based on Indodax cash, held coins, and pending Indodax order reserve only.

See [`docs/INDODAX_ONLY_RUNTIME.md`](./docs/INDODAX_ONLY_RUNTIME.md).

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

KiBot includes scanner modules for Indodax and Binance-to-Indodax lead-lag context. Scanner output is deduplicated, structured, and routed as evidence for downstream decisioning.

Highlights include:

- Indodax small-cap pump and continuation detection.
- Binance-to-Indodax lead-lag monitoring.
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
| [`ROOT_FILES_GUIDE.md`](./ROOT_FILES_GUIDE.md) | Plain-language guide explaining why root files must remain in place. |
| [`docs/FOLDER_STRUCTURE_OVERVIEW.md`](./docs/FOLDER_STRUCTURE_OVERVIEW.md) | Visual tree diagram and overview of the repository structure. |
| [`docs/ACCESS_GUIDE.md`](./docs/ACCESS_GUIDE.md) | Server access credentials, IPs, and synchronization protocol. |
| [`docs/MANIFESTO.md`](./docs/MANIFESTO.md) | Trading manifesto and core sovereignty principles. |
| [`Core/README.md`](./Core/README.md) | Core architecture and runtime overview. |
| [`Core/Decision/README.md`](./Core/Decision/README.md) | Decision authority, target boards, and opportunity tiering. |
| [`Core/Exchange/README.md`](./Core/Exchange/README.md) | Indodax exchange API adapter and HMAC signing. |
| [`Core/Scanner/README.md`](./Core/Scanner/README.md) | Scanner flow, delta filtering, and market signal routing. |
| [`Core/Executors/README.md`](./Core/Executors/README.md) | Execution layer, capital routing, and risk checks. |
| [`Core/Intelligence/README.md`](./Core/Intelligence/README.md) | AI orchestration, aggregator, learning loop, what-if simulation, and dashboards. |
| [`Core/Treasury/README.md`](./Core/Treasury/README.md) | Capital Governor, accounting truth, and daily loss limits. |
| [`Core/Security/README.md`](./Core/Security/README.md) | HMAC, vault, audit logging, and security posture. |
| [`Core/Notifications/README.md`](./Core/Notifications/README.md) | Throttled alerts, incident lifecycle, and Telegram notifications. |
| [`Core/Trading/README.md`](./Core/Trading/README.md) | Autonomous position sizing and risk calculations. |
| [`Core/Research/README.md`](./Core/Research/README.md) | Backtesting engine and walk-forward validation. |
| [`Core/Support/README.md`](./Core/Support/README.md) | Config, utilities, operational helpers, and system support tooling. |
| [`scripts/README.md`](./scripts/README.md) | Operational scripts overview, maintenance, and cloud capacity hunter. |
| [`bin/kibotctl`](./bin/kibotctl) | One-command operational wrapper. |
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
