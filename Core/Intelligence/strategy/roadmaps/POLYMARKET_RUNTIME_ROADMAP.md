# KiBot Sovereign — Polymarket Runtime Roadmap

> Purpose: convert Polymarket strategy from document into runtime modules.

---

## Current Maturity

Estimated runtime maturity: `35-50%`.

What exists:

- wallet env,
- Polymarket executor service,
- CLOB client package,
- scanner integration,
- state API port,
- basic balance/execution path.

What is missing:

- probability engine,
- resolution parser,
- liquidity simulator,
- evidence bundle,
- expiry risk scorer,
- robust mark-to-market,
- role-agent debate specific to event markets.

---

## Required Runtime Modules

### `polymarket_probability_engine.py`

Computes:

- market implied probability,
- estimated fair probability,
- edge points,
- confidence,
- contradiction score.

### `polymarket_resolution_risk.py`

Detects:

- ambiguous wording,
- official source dependency,
- expiry boundary risk,
- disputed resolution risk.

### `polymarket_liquidity_simulator.py`

Checks:

- spread,
- depth,
- slippage,
- exit feasibility,
- stale orderbook,
- marketable-limit feasibility.

### `polymarket_evidence_bundle.py`

Builds:

- official source evidence,
- search/news evidence,
- source quality,
- evidence freshness,
- contradiction map.

### `polymarket_position_tracker.py`

Tracks:

- open orders,
- fills,
- USDC balance,
- active bets,
- mark-to-market PnL,
- expiry exposure.

---

## Execution Rule

No Polymarket real-money mandate may execute unless it includes:

- market id,
- condition id,
- outcome,
- max price,
- size,
- estimated probability,
- edge,
- liquidity score,
- resolution risk,
- evidence quality,
- exit plan.

---

## Phases

1. Read-only health and metadata.
2. Probability/liquidity/resolution scoring.
3. Council role votes.
4. Limit-first executor hardening.
5. Dashboard Polymarket panel.
6. Combined daily GREEN integration.

