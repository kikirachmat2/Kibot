# 🏛️ Core — Pusat Logika Arsitektur KiBot (Core Engine)

Selamat datang di pusat komando **KiBot Sovereign**. Folder ini berisi seluruh logika inti sistem: mulai dari pembacaan radar pasar, pertimbangan kecerdasan buatan, kontrol brankas modal, hingga eksekusi order bursa.

---

## 🗺️ Peta Subdirektori `Core/`

Untuk mempermudah operator memahami arsitektur sistem tanpa harus membaca ribuan baris kode, seluruh fungsi telah dibagi ke dalam 11 departemen:

| Subdirektori | Departemen / Peran | Penjelasan Fungsi Singkat |
| :--- | :--- | :--- |
| [`Core/Decision/`](./Decision/README.md) | **Otak Pertimbangan** | Menimbang kelayakan sinyal, prioritas target koin, dan memvalidasi izin order. |
| [`Core/Intelligence/`](./Intelligence/README.md) | **Intelijen & AI** | Menganalisis berita pasar global, estimasi EV, simulasi pra-trade, dan Web Dashboard. |
| [`Core/Exchange/`](./Exchange/README.md) | **Pintu Gerbang Bursa** | Adaptor koneksi API resmi ke Indodax (cek saldo, ticker harga, order beli/jual). |
| [`Core/Executors/`](./Executors/README.md) | **Tangan Pelaksana** | Modul eksekusi order bursa yang cepat, presisi, dan aman (*High-Risk Runtime*). |
| [`Core/Scanner/`](./Scanner/README.md) | **Radar Pasar 24/7** | Memindai ratusan koin di pasar secara real-time mencari sinyal lonjakan harga (*High-Risk Runtime*). |
| [`Core/Treasury/`](./Treasury/README.md) | **Brankas & Bendahara** | Menegakkan batas rugi harian (*Hard Daily Loss Limit*) dan mencatat ekuitas kas/koin. |
| [`Core/Security/`](./Security/README.md) | **Garda Keamanan** | Enkripsi brankas API key (KiVault) dan otentikasi tanda tangan digital HMAC. |
| [`Core/Notifications/`](./Notifications/README.md) | **Saluran Komunikasi** | Pengirim notifikasi Telegram ter-throttle dan pengelolaan siklus insiden anti-spam. |
| [`Core/Trading/`](./Trading/README.md) | **Kalkulator Ukuran Posisi** | Menghitung alokasi modal optimal per posisi berdasarkan volatilitas pasar. |
| [`Core/Research/`](./Research/README.md) | **Laboratorium Riset** | Simulasi pengujian strategi dengan data historis masa lalu (*Backtesting & Walk-Forward*). |
| [`Core/Support/`](./Support/README.md) | **Divisi Perawatan** | Pembersih harddisk otomatis, pemantau telemetri server, dan fungsi pembantu sistem. |

---

## 📁 File Inti di Root `Core/`

| File | Penjelasan Fungsi |
| :--- | :--- |
| [`sovereign_council.py`](./sovereign_council.py) | **Dewan Musyawarah AI (Sovereign Council)**: Mengorkestrasi musyawarah bertingkat (Observer -> Diagnostician -> Strategist -> Arbiter) untuk mengevaluasi kondisi pasar dan kesehatan sistem. |
| [`risk_gate.py`](./risk_gate.py) | **Gerbang Pengendali Risiko**: Memeriksa parameter batas rugi, ambang batas minimum volume, dan spread sebelum order diizinkan jalan. |
| [`circuit_breaker.py`](./circuit_breaker.py) | **Sekring Pemutus Otomatis**: Memutus loop trading darurat jika terdeteksi anomali jaringan atau kegagalan berulang. |
| [`telegram_command_orchestrator.py`](./telegram_command_orchestrator.py) | **Penerima Perintah Remote**: Memproses instruksi kontrol jarak jauh yang dikirimkan operator melalui chat bot Telegram. |
| [`sovereign_state.py`](./sovereign_state.py) | **Manajer Status Sistem**: Mengatur persistensi dan pembacaan state operasional KiBot. |
| [`ki_brain.py`](./ki_brain.py) | *Compatibility Shim*: Mengarahkan impor lama ke modul Council modern. |
| [`sovereign_disk_cleaner.py`](./sovereign_disk_cleaner.py) | *Compatibility Shim*: Mengarahkan impor ke `Core/Support/sovereign_disk_cleaner.py`. |
| [`sovereign_notifier.py`](./sovereign_notifier.py) | *Compatibility Shim*: Mengarahkan impor ke `Core/Notifications/sovereign_notifier.py`. |
