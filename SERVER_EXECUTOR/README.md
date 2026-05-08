# SERVER_EXECUTOR: The High-Frequency Hand

Node eksekusi pesanan dengan latency rendah (Singapore).

## ⚡ Arsitektur Eksekusi

Sistem di sini menggunakan jembatan dua tahap:
1.  **Python Listener (`kibot_signal_listener.py`)**:
    *   Menerima instruksi JSON dari Batam.
    *   Mengonversi instruksi menjadi **Binary V2 Protocol**.
    *   Menambahkan Signature **HMAC-SHA256**.
    *   Push via UDP Lokal ke Kotlin Engine.
2.  **Kotlin MacEngine (`mac-engine-0.1.0-all.jar`)**:
    *   Mesin eksekusi inti (High Performance).
    *   Dengarkan port `10001` (UDP).
    *   Melakukan eksekusi ke API Indodax/Exchange.
    *   Memiliki Circuit Breaker internal untuk proteksi market.

## 📡 Koneksi
*   **Inbound**: `Port 9999` (UDP from Batam)
*   **Local Bridge**: `Port 10001` (UDP Python -> Kotlin)
*   **Outbound Feedback**: `Port 9997` (UDP to Batam)

## 📊 Monitoring
Kotlin engine menyediakan dashboard lokal di `http://localhost:8080` (tergantung config) untuk melihat status eksekusi secara visual.
