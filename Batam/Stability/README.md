# [Module] Stability (The Life Support)

This module ensures that KiBot is "Immortally Autonomous." It monitors the health of all processes and automatically revives them if they fail.

## Key Files

### 1. `ki_revival_engine.py` (The Lazarus Engine)
- **Role**: Process watchdog and restorer.
- **Responsibilities**:
    - Periodically checks if the `Manager`, `Scanners`, and `Executor` are alive.
    - If a process is dead or unresponsive (frozen), it kills and restarts it.
    - Logs "Resurrection" events to notify the owner of instability.
- **Usage**: Should be the first process started. It acts as the "Manager of Managers."

### 2. `ki_watchdog.py`
- **Role**: Resource monitor.
- **Responsibilities**:
    - Monitors RAM and CPU usage.
    - Clears logs or caches if the disk is full.

## Goal: 100% Uptime
This module is what allows the bot to run on a remote server (like OCI Ampere) without human supervision for weeks. It assumes that "Everything will eventually fail" and provides the logic to fix it.
