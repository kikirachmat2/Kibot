# 🏛️ Core/Exchange — Pintu Gerbang Koneksi Bursa

Folder ini berisi modul adaptor perantara antara sistem KiBot dengan **bursa crypto resmi** (saat ini difokuskan penuh pada Indodax). Modul di sini menangani komunikasi jaringan, pembacaan order book, cek saldo akun, dan pengiriman order API.

---

## 📁 Daftar File & Fungsinya

| File | Penjelasan Fungsi (Bahasa Awam) |
| :--- | :--- |
| [`indodax.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Exchange/indodax.py) | **Klien API Indodax**: Menangani autentikasi tanda tangan digital (HMAC-SHA512), query saldo rupiah & koin, pembacaan harga ticker terkini, serta pengiriman order open/cancel ke server Indodax. |
