# 🗺️ Peta Besar Struktur Repositori KiBot (Folder Structure Overview)

Dokumen ini adalah **peta navigasi utama** bagi operator untuk memahami seluruh repositori KiBot dalam sekali lihat tanpa perlu membuka baris kode program.

---

## 🌳 Pohon Arsitektur Repositori (Repository Tree)

```text
KiBot/
├── 📄 MasterNode.py            # [Jantung Sistem] Daemon orkestrator utama (service systemd server)
├── 📄 requirements.txt         # [Dependensi] Daftar paket Python resmi
├── 📄 pytest.ini               # [Testing] Konfigurasi engine pengujian otomatis
├── 📄 pyrightconfig.json       # [Type Checking] Konfigurasi pendeteksi error di IDE
├── 📄 .env                     # [Brankas Privat] API Key Indodax, token Telegram (lokal saja)
├── 📄 .env.example             # [Template] Contoh konfigurasi environment
├── 📄 .gitignore               # [Keamanan Git] Daftar file rahasia yang dilarang ke GitHub
├── 📄 README.md                # [Manual Utama] Dokumentasi pembuka repositori di GitHub
├── 📄 ROOT_FILES_GUIDE.md      # [Panduan Operator] Alasan teknis mengapa file root wajib di tempatnya
├── 📄 AGENTS.md                # [Instruksi AI] Aturan protokol bagi asisten coding otonom
│
├── 📁 Core/                    # [Pusat Logika Sistem KiBot]
│   ├── 📁 Decision/            # Menimbang kelayakan sinyal & menentukan prioritas koin
│   ├── 📁 Intelligence/        # Analisis AI pasar global, sentimen berita & web dashboard
│   ├── 📁 Exchange/            # Adaptor koneksi API resmi bursa Indodax
│   ├── 📁 Executors/           # Pelaksana eksekusi order riil di bursa (High-Risk)
│   ├── 📁 Scanner/             # Radar pemindai harga & lonjakan volume 24/7 (High-Risk)
│   ├── 📁 Treasury/            # Pengelola modal, akuntansi saldo & pelindung batas rugi harian
│   ├── 📁 Security/            # Enkripsi brankas API key (KiVault) & tanda tangan HMAC
│   ├── 📁 Notifications/       # Notifikasi Telegram ter-throttle & manajemen eskalasi insiden
│   ├── 📁 Trading/             # Manajemen ukuran posisi (position sizing) & rasio risiko
│   ├── 📁 Research/            # Laboratorium simulator pengujian data historis (Backtest)
│   └── 📁 Support/             # Pembersih harddisk otomatis & utilitas pemeliharaan sistem
│
├── 📁 bin/                     # [Alat Kendali Operator] Perintah satu pintu (kibotctl)
├── 📁 scripts/                 # [Skrip Pemeliharaan] Healthcheck, snapshot & hunter server
│   ├── 📁 archive/             # Arsip pengujian dan audit masa lalu yang sudah selesai
│   ├── 📁 diagnostics/         # Alat investigasi forensik saat terjadi anomali data
│   └── 📁 research/            # Skrip analisis kuantitatif & kalibrasi performa
│
├── 📁 docs/                    # [Pusat Dokumentasi] Panduan arsitektur, akses & peta sistem
│   ├── 📄 ACCESS_GUIDE.md      # Protokol IP dan akses SSH server
│   ├── 📄 MANIFESTO.md         # Filosofi trading dan prinsip kedaulatan KiBot
│   └── 📄 FOLDER_STRUCTURE_... # Dokumen ini (Peta besar repositori)
│
├── 📁 state/                   # [Basis Data Runtime] File JSON transaksi, saldo & jurnal keputusan
├── 📁 config/                  # [Konfigurasi] File pengaturan strategi & batasan trading
├── 📁 logs/                    # [Catatan Operasional] File log aktivitas daemon server
├── 📁 tests/                   # [Uji Otomatis] Seluruh unit test penjamin kualitas sistem
└── 📁 android/                 # [Aplikasi Android] Project pemantau KiBot untuk smartphone
```

---

## 🧭 Ringkasan 1 Baris per Folder Utama

| Folder Top-Level | Tugas Utama (Bahasa Awam) |
| :--- | :--- |
| **`Core/`** | Pusat seluruh otak, keputusan, keamanan, dan eksekusi transaksi trading. |
| **`bin/`** | Rumah bagi `kibotctl` — tombol kendali utama operator untuk cek status, restart, dan cek kesehatan. |
| **`scripts/`** | Skrip pembantu pemeliharaan, pencadangan database, dan pemburu server cloud. |
| **`docs/`** | Arsip lengkap dokumen panduan, filosofi trading, dan petunjuk operasional. |
| **`state/`** | Database lokal penyimpan status transaksi harian, saldo terkini, dan riwayat order. |
| **`config/`** | Pengaturan parameter trading, batas risiko per koin, dan preferensi sistem. |
| **`logs/`** | Rekaman peristiwa teknis server untuk mempermudah investigasi jika ada kendala. |
| **`tests/`** | Pasukan penguji otomatis yang memastikan setiap baris kode bekerja sesuai rencana. |
| **`android/`** | Kode sumber aplikasi mobile Android untuk monitoring status KiBot dari HP. |

---

*Setiap folder di dalam repositori ini kini memiliki identitas dan peran yang jelas tanpa tumpang tindih.*
