# KiBot Observability and Dashboard Spec

## Dashboard Mission
The dashboard must answer:
- is KiBot alive?
- is KiBot safe to trade?
- what is total equity?
- what is realized/unrealized PnL?
- what did KiBot do?
- what did KiBot reject?
- what needs operator help?

## Required Panels
1. Sovereign header: runtime mode, total equity, PnL, risk state.
2. Delegation graph: operator, council, scanner, AI brain, Indodax executor, verifier, janitor/system commander.
3. Capital Governor: budget, daily loss state, green lock, open orders.
4. RiskGate: last pass/reject and exact reason.
5. Candidate Intelligence: top candidates, rejected candidates, missed opportunities.
6. Source and Provider Health: AI/search/source health and stale evidence.
7. Inventory Utilization: services, models, tools, APIs, state files.
8. GitHub/Server Drift: local HEAD, origin HEAD, dirty files.
9. Backup/Restore: last backup and protected state.
10. Event Trail: trade events, system events, recovery events, Telegram alerts.

## Design Rule
Dashboard may be dense. Telegram must stay sparse.
