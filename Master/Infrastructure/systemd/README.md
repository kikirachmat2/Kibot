# 🛠️ KiBot Infrastructure: Systemd Services

Service definitions for persistent, autonomous operation on Linux nodes.

## Responsibility
- **Persistence**: Ensuring KiBot and its support services start automatically on boot and stay running.
- **Monitoring**: Integration with systemd's watchdog and recovery mechanisms.
- **Orchestration**: Managing the startup order of dependent services (e.g., High Command before Healer).

## Key Service Units
- `kibot-high-command.service`: The primary service for the KiBot Master node.
- `executor-healer.service`: Background healer specifically for the execution node.
- `executor-healer.timer`: Periodic trigger for health checks on the executor.
