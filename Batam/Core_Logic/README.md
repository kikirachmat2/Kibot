# [Module] Core Logic (The Brain Control)

This module is the heartbeat of KiBot. It orchestrates all incoming signals, manages the trading state, and acts as the final decision-maker before any trade is sent to the executor.

## Key Files

### 1. `kibot_manager.py` (The General)
- **Role**: Central coordinator for all trading activities.
- **Responsibilities**:
    - Listens for signals from the Scanner network (via UDP).
    - Implements the "Trinity Gates" (Health, Risk, and Math checks) to filter entries.
    - Manages global state variables (BTC price, active positions, daily PnL).
    - Acts as a local dashboard server (HTTP) for real-time monitoring.
- **Usage**: Usually run as a persistent service. It requires Redis for state persistence and a local `.env` for configuration.

### 2. `ki_brain.py` (The Advisor)
- **Role**: High-level intelligence and research coordinator.
- **Responsibilities**:
    - Conducts background research on market catalysts and news.
    - Fetches sentiment data from external sources (Polymarket, Fear & Greed, Funding Rates).
    - Builds a "World Model" that the AI Critic uses to adjust risk postures.
- **Usage**: Internal module used by the Manager to get "advisory" context.

### 3. `trinity_governor.py` (The Overseer)
- **Role**: Watchdog and automated healing script.
- **Responsibilities**:
    - Monitors logs for errors or significant losses.
    - Uses AI (Ollama/Copilot) to suggest and apply "self-healing" bash commands.
    - Performs "Midnight Evolution" to research and suggest strategy improvements.
- **Usage**: Run as a background daemon to ensure system stability.

## How to Interact
Most logic in this directory is triggered by signals. You can simulate a signal using the tools in the `Support/Audit & Testing` folder.

## Audit Warning
Both `kibot_manager.py` and its dependencies are becoming monolithic. Any major changes here should be preceded by a full state backup.
