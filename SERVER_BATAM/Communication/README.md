# [Module] Communication (The Messenger)

This module handles all external reporting. It is the only way the system talks to the human owner.

## Key Files

### 1. `kibot_telegram_notifier.py`
- **Role**: Telegram bot interface.
- **Responsibilities**:
    - Sends trade alerts (Buy/Sell/Profit).
    - Sends critical system alerts (Hard Stop hit, AI Offline).
- **Usage**: Integrated into the Manager's main loop. Requires `TELEGRAM_BOT_TOKEN` in `.env`.

## KiBot Communication Hub (v9.1.1)

## Architecture Overview
Sistem komunikasi KiBot Trinity dibagi menjadi dua jalur utama untuk efisiensi dan keamanan:

1. **Telegram Commander** (`../Core_Logic/telegram_commander.py`)
   - **Fungsi**: "Telinga" Batam.
   - **Interaksi**: Mendukung perintah interaktif (`/status`, `/pnl`, `/emergency_stop`).
   - **Status**: Selalu aktif sebagai systemd service (`kibot-commander.service`).

2. **KiBot Notifier** (`kibot_notifier.py`)
   - **Fungsi**: "Mulut" Batam.
   - **Interaksi**: Mengirimkan alert otomatis (Trade sukses, RAM penuh, Daily Report) melalui Event-Bus di `state/events/`.
   - **Fitur**: Memiliki Rate-Limiting (Max 5 pesan/menit) agar bot tidak kena ban oleh Telegram.

## Setup
Keduanya menggunakan token yang sama dari `SERVER_BATAM/Support/ki_config.py`.

## Maintenance
- File lama yang tidak kompatibel dipindahkan ke folder `Legacy/`.
- Log aktivitas komunikasi dapat dicek di `Infrastructure/logs/communication.log`.
