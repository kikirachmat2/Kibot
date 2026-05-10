# ⚙️ KiBot Infrastructure: Automation & Self-Healing

Automated deployment, monitoring, and self-recovery logic for the KiBot node.

## Responsibility
- **Self-Healing**: Monitoring the bot processes and restarting them if they crash or hang.
- **Auto-Deployment**: Scripts for pulling updates and redeploying the KiBot cluster automatically.
- **Service Management**: Integration with systemd to ensure persistent background operation.

## Key Components
- `trinity_monitor.py`: The primary health monitor that checks the status of all core components.
- `trinity_healer.py`: The automated recovery engine that performs corrective actions when the monitor detects a failure.
- `auto_deploy_batam.sh`: A production-ready script for zero-downtime updates and synchronization from the source repository.
- `adb_bridge.sh`: Manages the ADB tunnel for communication with Android monitoring nodes.
