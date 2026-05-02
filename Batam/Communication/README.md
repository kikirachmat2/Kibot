# [Module] Communication (The Messenger)

This module handles all external reporting. It is the only way the system talks to the human owner.

## Key Files

### 1. `kibot_telegram_notifier.py`
- **Role**: Telegram bot interface.
- **Responsibilities**:
    - Sends trade alerts (Buy/Sell/Profit).
    - Sends critical system alerts (Hard Stop hit, AI Offline).
    - Receives commands from the owner (e.g., `/status`, `/stop`, `/resume`).
- **Usage**: Integrated into the Manager's main loop. Requires `TELEGRAM_BOT_TOKEN` in `.env`.

## Philosophy
"No Noise, Only Signal." The communication layer is designed to only disturb the owner when something significant happens (Profits) or something critical fails.
