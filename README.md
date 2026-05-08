# KiBot Trinity: Sovereign Autonomous Trading Mesh

Sistem trading mesh otonom yang terdistribusi di 3 node global (Tokyo, Singapore, Batam) untuk eksekusi sub-millisecond dengan pengawasan risiko terpusat.

## 🏛️ Hirarki Komando (Command Structure)

Sistem ini dipegang oleh **Satu Komando Tunggal** yang berpusat di **SERVER_BATAM**.

1.  **MAIN COMMANDER (The Brain - Batam)**:
    *   **Logic**: `kibot_brain_gateway.py`
    *   **Fungsi**: Pengambil keputusan akhir, Veto trade, monitoring PnL global, dan gerbang komunikasi ke User via Telegram.
    *   **Sovereign Arbitrator**: Menjaga "kesadaran" modal. Jika rugi >5%, Batam mematikan seluruh mesh secara otonom.

2.  **THE SENSOR (Scanner - Tokyo)**:
    *   **Logic**: `ki_global_scanner_mesh.py`
    *   **Fungsi**: Scraper harga & anomali market. Mengirimkan signal mentah ke Batam via UDP (Port 9998).
    *   **Heartbeat**: Mengirim status kesehatan node ke Batam setiap 10 detik.

3.  **THE HAND (Executor - Singapore)**:
    *   **Logic**: `kibot_signal_listener.py` -> `mac-engine (Kotlin)`
    *   **Fungsi**: Eksekutor pesanan. Menerima instruksi dari Batam, mengonversi ke Binary V2 (HMAC Signed), dan menembak langsung ke engine eksekusi Kotlin.

## 📡 Jalur Komunikasi

| Jalur | Protokol | Port | Deskripsi |
| :--- | :--- | :--- | :--- |
| Scanner -> Batam | UDP | 9998 | Signal Anomali & Heartbeat |
| Batam -> Executor | UDP | 9999 | Instruksi Eksekusi (Vetoed) |
| Executor -> Batam | UDP | 9997 | Laporan Eksekusi (Feedback Loop) |
| User -> Batam | HTTP/TG | - | Manual Overide & Monitoring |

## 🛡️ Keamanan & Integritas
*   **HMAC-SHA256**: Semua paket Binary antara Python dan Kotlin di Singapore harus ditandatangani secara digital.
*   **Tailscale Mesh**: Komunikasi antar server berjalan di dalam jaringan privat Tailscale.
*   **PnL Hard Lock**: Proteksi saldo otomatis di level Brain.

---
*Created by Antigravity AI for KiBot Sovereign Deployment.*