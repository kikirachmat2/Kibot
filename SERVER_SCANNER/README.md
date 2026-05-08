# SERVER_SCANNER: The Sensor Node

Node ini bertugas sebagai "Mata" yang memantau anomali di berbagai exchange secara real-time.

## 📡 Komponen Utama

1.  **Exchange_Scrapers/ki_global_scanner_mesh.py**:
    *   Mesin scraper utama yang mendukung Binance, Bybit, Kucoin, dll.
    *   Mengirimkan signal anomali via UDP ke Batam.
    *   **Heartbeat Thread**: Melapor ke Batam tiap 10 detik agar sistem tahu node ini masih hidup.
2.  **Deployment/systemd**:
    *   Konfigurasi untuk menjalankan scanner sebagai service background yang otomatis restart jika crash.

## 🚀 Jalur Data
*   **Target**: `SERVER_BATAM_IP:9998` (UDP)
*   **Format**: JSON Packet (v1)

## 🔐 Keamanan
Akses ke node ini menggunakan SSH Key yang ada di folder `Auth/`. Pastikan public key sudah terdaftar di server target.
