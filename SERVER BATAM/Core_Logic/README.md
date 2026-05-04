# [Module] Core Logic (The Brain Control)
 
This module is the heartbeat of KiBot. It orchestrates all incoming signals, manages the trading state, and acts as the final decision-maker before any trade is sent to the executor.

> [!IMPORTANT]
> **v7.0 Update**: Core logic has been refactored for **Sub-Millisecond Egress**. AI Veto calls are now non-blocking (async) to prevent hot-path latency.

## Key Files

### 1. `kibot_manager.py` (The General)
- **Role**: Central coordinator for all trading activities.
- **Optimizations**:
    - **Async AI Veto**: Signal validation is now decoupled from the entry loop.
    - **Unified Networking**: Single-point egress for UDP signals to Singapore/Batam.
    - **Modular Config**: Powered by `Support/ki_config.py`.
- **Usage**: Requires Redis for state and `Support/` modules for helper logic.

### 2. `trinity_governor.py` (The Overseer)
- **Role**: Watchdog and automated healing script.
- **Security Hardening**:
    - **Command Allowlisting**: Only safe, pre-approved bash patterns are allowed.
    - **Secure Subprocess**: Replaced `shell=True` with list-based execution to prevent command injection.
- **Usage**: Monitors logs and performs automated self-healing and "Midnight Evolution".

### 3. `ki_brain.py` (The Advisor)
- **Role**: High-level intelligence and research coordinator.
- **Responsibilities**: Builds the "World Model" used for strategic posture adjustments.

## Core Infrastructure
- **[Support/](file:///Users/kiki/Documents/Web%20Develop/KiBot/Batam/Support/)**: Contains `ki_config.py` (Global Constants) and `ki_utils.py` (Shared Helpers).

## Performance & Safety
- **Latency**: Hot-path entry logic is < 1ms.
- **Security**: The Governor is now strictly firewalled against unauthorized AI-suggested commands.

## Audit Warning
Major logic is now modularized into `Support/`. Do not hardcode IPs or API URLs in `Core_Logic`; use `ki_config` instead.
