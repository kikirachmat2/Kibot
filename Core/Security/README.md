# 🛡️ Core/Security — Garda Keamanan & Enkripsi Kunci (Sovereign Shield)

Folder ini bertindak sebagai **Benteng Keamanan (Security & Cryptography Layer)** KiBot. Tugas utamanya adalah mengenkripsi kunci rahasia API, memvalidasi tanda tangan digital paket data UDP, memverifikasi integritas file database, dan mencegah manipulasi data dari pihak luar.

---

## 📁 Daftar File & Fungsinya

| File | Penjelasan Fungsi (Bahasa Awam) |
| :--- | :--- |
| [`ki_vault.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Security/ki_vault.py) | **Brankas Enkripsi (KiVault)**: Membaca file `.env.kiv` yang terenkripsi dan memuat kunci API langsung ke memori RAM saat server menyala tanpa pernah meninggalkan jejak teks biasa (*plaintext*) di harddisk. |
| [`ki_vault_cli.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Security/ki_vault_cli.py) | **Alat Kontrol Brankas**: Program baris perintah untuk mengunci (*encrypt*), membuka (*decrypt*), atau merotasi kunci brankas KiVault. |
| [`kibot_crypto_auth.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Security/kibot_crypto_auth.py) | **Otentikasi Kriptografi HMAC**: Memberikan stempel tanda tangan digital (HMAC-SHA256) pada setiap paket sinyal scanner. Mencegah sinyal palsu atau injeksi data asing. |
| [`kibot_security.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Security/kibot_security.py) | **Audit Integritas File**: Memeriksa sidik jari (*hash*) file database state penting (seperti `learning_state.json`) agar sistem tahu jika ada file yang korup atau terhapus. |

---

## 🔒 Standar Keamanan Berdaulat (Security Posture)
1. **Zero Secret in Git**: Dilarang keras men-commit file kunci `.env`, file `.pem`, atau password ke GitHub.
2. **Fail-Closed Security**: Jika tanda tangan HMAC sebuah sinyal tidak cocok dengan `KIBOT_SECRET`, sinyal tersebut langsung dibuang seketika tanpa dieksekusi.
3. **Penyaringan Data Usang (TTL)**: Sinyal pasar yang berumur lebih dari 10–15 detik otomatis ditolak untuk mencegah pembelian harga lama (*stale order*).
