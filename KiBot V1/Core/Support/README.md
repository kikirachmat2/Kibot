# 🛠️ Core/Support — Perawatan, Pemeliharaan & Utilitas Sistem

Folder ini bertindak sebagai **Divisi Pemeliharaan & Utilitas (Support Layer)** KiBot. Tugas utamanya adalah merawat kebersihan disk server, memantau kesehatan hardware/software, menyediakan fungsi pembantu (*helper*), dan mengelola konfigurasi dinamis sistem.

---

## 📁 Daftar File Utama & Fungsinya

| File | Penjelasan Fungsi (Bahasa Awam) |
| :--- | :--- |
| [`sovereign_disk_cleaner.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/sovereign_disk_cleaner.py) | **Pembersih Disk Otomatis**: Memantau kapasitas harddisk server; memangkas log raksasa dan cache usang jika pemakaian disk melebihi batas aman. |
| [`sovereign_janitor.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/sovereign_janitor.py) | **Petugas Kebersihan Runtime**: Menjalankan service pembersihan berkala dan memastikan daemon Ollama/AI tidak mengalami kebocoran memori. |
| [`ki_config.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/ki_config.py) | **Pusat Konfigurasi Bersama**: Menyimpan konstanta path direktori, nomor port UDP/TCP, zona waktu WIB (UTC+7), dan batas nominal transaksi. |
| [`dynamic_config.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/dynamic_config.py) | **Pengatur Pengaturan Dinamis**: Mengizinkan perubahan parameter trading tanpa harus me-restart seluruh proses daemon. |
| [`server_telemetry.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/server_telemetry.py) | **Telemetri Kesehatan Server**: Mengukur beban CPU, sisa RAM, dan suhu server untuk dilaporkan ke dashboard. |
| [`telegram_throttle.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/telegram_throttle.py) | **Peredam Frekuensi Notifikasi**: Membatasi antrean pengiriman pesan Telegram agar akun bot tidak terkena penalti *Too Many Requests* (429). |
| [`system_commander.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/system_commander.py) | **Komandan Sistem**: Mengoordinasikan instruksi operasional yang dikirimkan via remote command Telegram. |
| [`churn_guard.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/churn_guard.py) | **Pelindung Overtrading (Anti-Churn)**: Mencegah sistem melakukan transaksi jual-beli terlalu sering pada koin yang sama dalam hitungan menit. |
| [`recovery_mode_policy.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/recovery_mode_policy.py) | **Kebijakan Mode Pemulihan**: Mengatur langkah darurat otomatis saat sistem mendeteksi kegagalan koneksi bursa. |
| [`round_trip_accounting.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/round_trip_accounting.py) | **Akuntansi Transaksi Lengkap**: Menghitung siklus lengkap trading (Beli -> Hold -> Jual) agar kalkulasi profit/rugi akurat hingga digit pecahan terkecil. |
