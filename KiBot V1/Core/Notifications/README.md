# 📱 Core/Notifications — Saluran Notifikasi & Komunikasi Telegram

Folder ini bertindak sebagai **Saluran Komunikasi Resmi (Notification Layer)** KiBot. Tugas utamanya adalah mengirimkan laporan trading, pesan darurat, dan ringkasan status harian ke Telegram operator dengan mematuhi prinsip kebersihan notifikasi (*notification hygiene*): **tidak melakukan spam berulang untuk masalah yang sama**.

---

## 📁 Daftar File & Fungsinya

| File | Penjelasan Fungsi (Bahasa Awam) |
| :--- | :--- |
| [`sovereign_notifier.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Notifications/sovereign_notifier.py) | **Pengirim Notifikasi Berdaulat**: Menghubungkan KiBot ke Telegram Bot API. Mengatur antrean pesan (*outbox*), pembatasan frekuensi (*throttling*), dan format teks Markdown. |
| [`incident_lifecycle.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Notifications/incident_lifecycle.py) | **Manajer Siklus Insiden**: Mencegah spam Telegram dengan tangga eskalasi: kirim alert `URGENT` saat pertama kali insiden terjadi, 1x konfirmasi, lalu hening (*mute*) jika penyebabnya tidak berubah, dan hanya mengirimkan ringkasan `DAILY_STATUS` setelah 24 jam. |
| [`telegram_exception_notifier.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Notifications/telegram_exception_notifier.py) | **Pemberitahu Error Sistem**: Menangkap error kritis/unhandled exception pada runtime server dan merangkumnya agar operator langsung mengetahui akar masalah. |

---

## 🛡️ Filosofi Notifikasi Operator
1. **Telegram adalah Saluran Terbatas**: Notifikasi hanya dikirim untuk hal-hal yang benar-benar membutuhkan perhatian manusia atau rangkuman hasil eksekusi otomatis.
2. **Selesaikan Dulu, Baru Lapor**: Sistem memprioritaskan penyembuhan mandiri (*auto-remediation*) terlebih dahulu pada masalah teknis, lalu melaporkan hasilnya.
3. **Laporan Harian Tetap Wajib**: Kondisi yang persistent tidak boleh hilang tanpa jejak; laporan status harian tetap disajikan setiap pagi.
