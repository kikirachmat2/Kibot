# KiBot Server Inventory

## Runtime Scope
- Target server: Batam.
- Canonical runtime manager: `systemd`.
- Operator entrypoint: `bin/kibotctl`.
- Trading venue aktif: Indodax spot only.
- Canonical money truth: `state/live_truth.json`.

## Canonical Services
| Service | Purpose |
|---|---|
| `kibot-master` | Main orchestration loop |
| `kibot-scanner` | Indodax market scanner |
| `kibot-executor` | Indodax live executor |
| `kibot-live-truth` | Canonical equity/PnL writer |
| `kibot-capital-governor` | Risk/accounting governor |
| `kibot-ai-scout` | AI/advisory patrol and diagnostics |
| `kibot-dashboard` | Web dashboard/control plane |
| `ollama` | Local model runtime |
| `redis-server` | Shared cache/coordination |

## Retired Scope
External wallet, chain, and prediction-market route runners are retired and must stay disabled unless a future architecture decision explicitly reintroduces them.

## State Contract
- `state/live_truth.json`: total equity, cash, held coin value, realized/unrealized PnL, risk state.
- `state/active_trades.json`: live Indodax positions.
- `state/orders/`: order tracking and pending order records.
- `state/trade_history/`: append-only trade history.
- `state/decision_journal/`: scanner/council/executor audit trail.

## Safety Notes
- Never commit `.env`, keys, tokens, seed phrases, or decrypted vault material.
- Telegram is exception-only plus important trade summaries.
- Live trading remains behind explicit runtime gates and deterministic checks.
- Runtime docs must be updated whenever systemd service inventory changes.
