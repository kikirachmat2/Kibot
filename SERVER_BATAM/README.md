# SERVER_BATAM: The Central Brain

Folder ini berisi logika pusat komando (C2) untuk seluruh jaringan KiBot.

## 🧠 Komponen Utama

1.  **kibot_brain_gateway.py**: 
    *   Menerima signal dari Scanner.
    *   Melakukan kalkulasi Kelly Criterion dan Veto trading.
    *   Dengarkan feedback dari Executor.
2.  **sovereign_arbitrator.py**:
    *   Pengawas risiko (Risk Manager).
    *   Membaca `sovereign_state.json` untuk mengecek apakah batas rugi harian tercapai.
3.  **telegram_commander.py**:
    *   Interface bot Telegram untuk `/status`, `/run_all`, dan notifikasi trade real-time.
4.  **kibot_node_agent.py**:
    *   Agen lokal yang memungkinkan Batam mengontrol service systemd di node lain via API.

## 🛠️ Setup & Config
Pastikan file `.env` memiliki:
*   `TELEGRAM_BOT_TOKEN`
*   `TELEGRAM_CHAT_ID`
*   `KIBOT_MANAGER_ENV_FILE`

## 📡 Port Map
*   `9998`: Inbound UDP (From Scanner)
*   `9997`: Inbound UDP (From Executor Feedback)
*   `9991`: Outbound HTTP (To Node Agents)
