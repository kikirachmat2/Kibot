# Panduan File Root KiBot (Root Files Guide)

Dokumen ini ditujukan untuk **operator sistem KiBot** (termasuk yang bukan programmer) agar memahami secara transparan mengapa file-file tertentu **wajib berada di direktori root** (`/`) dan tidak boleh dipindahkan ke dalam folder lain.

---

## 🏛️ Mengapa Ada File di Luar Folder?

Dalam dunia pengembangan software (terutama Python dan Linux), beberapa file memiliki fungsi sebagai **titik masuk utama (entrypoint)** atau **konfigurasi global** yang dicari otomatis oleh sistem operasi, tool otomatisasi, dan engine pengujian. 

Jika file-file ini dipindahkan ke dalam folder lain, sistem operasi atau tool pendukung tidak akan dapat menemukannya secara otomatis, yang dapat mengakibatkan layanan server gagal berjalan (*crash*).

Berikut adalah rincian lengkap 9 file yang wajib berada di root:

---

## 📋 Daftar File Root & Fungsinya

### 1. `MasterNode.py` (File Program Utama)
* **Apa ini?**: "Jantung" dan koordinator utama sistem KiBot saat berjalan di server.
* **Fungsinya**: Menjalankan perputaran Sovereign Council (Dewan Keputusan), menerima sinyal trading dari Scanner, memeriksa batas risiko modal, dan mengoordinasikan eksekusi.
* **Kenapa Wajib di Root?**: Layanan otomatis Linux di server (`kibot-master.service` pada systemd) secara permanen diprogram untuk mengeksekusi file di alamat `/home/ubuntu/KiBot/MasterNode.py`. Jika dipindah, service server akan mati (*failed to start*).

### 2. `requirements.txt` (Daftar Kebutuhan Modul)
* **Apa ini?**: Daftar belanja resmi paket/library Python yang dibutuhkan KiBot untuk bisa berjalan.
* **Fungsinya**: Digunakan oleh perintah `pip install -r requirements.txt` saat pertama kali memasang KiBot di server baru.
* **Kenapa Wajib di Root?**: Ini adalah konvensi universal seluruh ekosistem pemrograman Python di seluruh dunia. Tool deployment otomatis mencari file ini di root.

### 3. `pytest.ini` (Pengaturan Uji Otomatis)
* **Apa ini?**: Buku petunjuk untuk engine penguji otomatis (`pytest`).
* **Fungsinya**: Memberitahu sistem pengujian di mana letak folder tes (`tests/`), aturan apa saja yang harus divalidasi, dan bagaimana laporan hasil tes ditampilkan.
* **Kenapa Wajib di Root?**: Program `pytest` secara default memindai folder paling atas tempat perintah dijalankan.

### 4. `pyrightconfig.json` (Pengatur Deteksi Error Kode)
* **Apa ini?**: Konfigurasi untuk type checker (pemeriksa kesehatan penulisan kode di IDE seperti VS Code atau Antigravity).
* **Fungsinya**: Membantu IDE memahami struktur modul `Core/` sehingga tidak memunculkan peringatan error palsu (*false positive*).
* **Kenapa Wajib di Root?**: Language Server di IDE membaca konfigurasi ini tepat di folder kerja utama proyek.

### 5. `.env` (File Kunci & Rahasia — Privat)
* **Apa ini?**: "Brankas kunci" yang berisi API Key Indodax, token bot Telegram, ID chat, dan flag pengaturan live trading.
* **Fungsinya**: Memberikan akses ke bursa dan jalur komunikasi Telegram tanpa perlu menuliskan password/kunci rahasia langsung di dalam kode.
* **Kenapa Wajib di Root?**: Library pembaca lingkungan (`python-dotenv`) secara otomatis mencari file bernama `.env` di folder tempat program pertama kali dipanggil. File ini sengaja disembunyikan (berawalan titik) dan **tidak pernah diunggah ke GitHub** demi keamanan saldo Anda.

### 6. `.env.example` (Contoh Cetak Biru Kunci)
* **Apa ini?**: Salinan kosong dari `.env` tanpa isi kunci rahasia.
* **Fungsinya**: Sebagai panduan bagi operator saat menyiapkan server baru tentang variabel apa saja yang wajib diisi.
* **Kenapa Wajib di Root?**: Konvensi standar GitHub agar developer/operator langsung melihat contoh konfigurasi saat membuka repositori.

### 7. `.gitignore` (Daftar File Terlarang untuk GitHub)
* **Apa ini?**: Daftar hitam file yang dilarang dikirim ke GitHub publik/privat.
* **Fungsinya**: Mencegah file rahasia (seperti `.env`), file database transaksi harian (`state/`), dan cache sementara agar tidak ter-upload ke internet.
* **Kenapa Wajib di Root?**: Git membaca aturan pengabaian ini dari root direktori kerja.

### 8. `README.md` (Halaman Depan Dokumentasi)
* **Apa ini?**: Buku manual dan profil utama proyek KiBot.
* **Fungsinya**: Menjelaskan apa itu KiBot, arsitektur 3 server, perintah kontrol operator (`bin/kibotctl`), dan status sistem.
* **Kenapa Wajib di Root?**: Standar wajib GitHub. File ini yang otomatis dirender menjadi halaman utama ketika repositori dibuka di browser.

### 9. `AGENTS.md` (Instruksi Agen AI Mandiri)
* **Apa ini?**: Buku panduan protokol untuk agen AI (Codex, Aider, Copilot, Antigravity) yang bekerja memprogram repositori ini.
* **Fungsinya**: Memastikan setiap asisten AI mematuhi aturan ketat: tidak boleh membocorkan rahasia, dilarang mengubah parameter risiko trading tanpa izin, dan menghormati systemd sebagai sumber kebenaran server.
* **Kenapa Wajib di Root?**: Sistem AI membaca instruksi agen dari root workspace saat memulai sesi kerja.

---

## 🛑 Panduan Tindakan untuk Operator

| File | Boleh Diedit Manual? | Catatan Penting |
| :--- | :--- | :--- |
| `MasterNode.py` | ❌ **JANGAN** | Sangat berisiko memicu crash pada service trading live. |
| `requirements.txt` | ⚠️ **HATI-HATI** | Hanya diedit jika menambah library Python baru. |
| `pytest.ini` | ❌ **JANGAN** | Dikelola otomatis untuk konsistensi pengujian. |
| `pyrightconfig.json` | ❌ **JANGAN** | Menjaga panel Problems di IDE tetap bersih (0 error). |
| `.env` | ✅ **BOLEH** | Boleh diedit untuk mengganti API key, token Telegram, atau mode trading. |
| `.env.example` | ✅ **BOLEH** | Diperbarui jika ada variabel baru di `.env`. |
| `.gitignore` | ⚠️ **HATI-HATI** | Jangan hapus baris `.env` atau `state/`. |
| `README.md` | ✅ **BOLEH** | Bebas diperbarui untuk mencatat catatan operasional. |
| `AGENTS.md` | ✅ **BOLEH** | Diperbarui jika ada instruksi kerja baru untuk asisten coding AI. |

---

*Dengan panduan ini, direktori root KiBot kini bersih, rapi, dan setiap file memiliki fungsi teknis yang esensial.*
