# [Module] Global State (System Memory)

This directory acts as the "Short-Term Memory" of KiBot. It contains JSON files that store the current system state, preventing data loss if a process restarts.

## Key Files

### 1. `brain_status.json`
- Stores the latest market intel, world model, and AI Critic analysis.
- Used by the Dashboard to display current market "Pulse."

### 2. `daily_summary.json`
- Tracks today's trading performance (PnL, win rate, total trades).
- Reset every midnight by the Governor.

### 3. `urgent_scout.json`
- The IPC (Inter-Process Communication) signal file used to trigger immediate AI research on specific assets.

## Caution
Do **NOT** manually edit these files while the bot is running unless you are an advanced user. The Manager frequently overwrites them.
