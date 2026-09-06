# 🛰️ Core/Scanner — Radar Pendeteksi Peluang Pasar 24/7

Folder ini bertindak sebagai **Radar Pengawas Pasar (Scanner Layer)** KiBot. Tugas utamanya adalah memindai ratusan aset crypto di bursa secara *real-time*, mendeteksi lonjakan volume, memantau pergerakan harga cepat, dan mengirimkan paket sinyal terenkripsi (HMAC-signed) ke Sovereign Council untuk dievaluasi.

> [!IMPORTANT]
> **Status Risiko**: **SANGAT TINGGI (High-Risk Runtime)**.
> File [`engine.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/engine.py) terikat langsung dengan service systemd `kibot-scanner.service` di server SG1. Dilarang mengubah struktur atau me-rename file ini tanpa rencana migrasi teruji.

---

## 📁 Daftar File & Fungsinya

| File | Penjelasan Fungsi (Bahasa Awam) |
| :--- | :--- |
| [`engine.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/engine.py) | **Orkestrator Scanner Utama**: Mengatur perputaran loop pemindaian, menyaring lonjakan harga signifikan (*delta filter*), membungkus sinyal dengan tanda tangan keamanan HMAC, dan mengirimnya via socket UDP ke MasterNode. |
| [`indodax_binance_leadlag_scanner.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/indodax_binance_leadlag_scanner.py) | **Radar Lead-Lag Binance→Indodax**: Memantau koin-koin di Binance yang sudah mulai naik duluan beberapa detik sebelum harga di Indodax merespons, memberikan keuntungan curi start (*alpha*). |
| [`indodax_market_scanner.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/indodax_market_scanner.py) | **Pemindai Pasar Indodax**: Membaca ringkasan seluruh ticker pasar Indodax (kenaikan 24 jam, volume transaksi, dan spread bid-ask). |
| [`ki_indodax_smallcap_scanner.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/ki_indodax_smallcap_scanner.py) | **Radar Koin Small-Cap**: Mendeteksi lonjakan mendadak (*pump*) pada koin-koin berkapitalisasi kecil dengan proteksi anti-jebakan likuiditas (*tick-trap*). |
| [`ki_universal_leadlag_scanner.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/ki_universal_leadlag_scanner.py) | **Radar Global Multi-Exchange**: Membaca sentimen dan tren pergerakan harga crypto di level makro dunia. |
| [`scanner_executor_contract.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/scanner_executor_contract.py) | **Kontrak Sinkronisasi Rute**: Memastikan koin yang terdeteksi scanner memiliki pasangan trading yang valid dan bisa dieksekusi oleh modul Executor. |
| [`scanner_health.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/scanner_health.py) | **Pemeriksa Kesehatan Scanner**: Mengecek apakah loop scanner masih terus memompa data atau mengalami kemacetan koneksi. |
| [`scanner_health_runner.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/scanner_health_runner.py) | **Runner Kesehatan**: Skrip mandiri pemanggil healthcheck scanner. |
| [`source_proof.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/source_proof.py) | **Verifikasi Sumber Data**: Memvalidasi integritas timestamp data harga agar sistem tidak menggunakan data basi (*stale price*). |
