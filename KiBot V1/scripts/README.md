# 🛠️ scripts — Skrip Operasional & Pemeliharaan KiBot

Folder ini berisi kumpulan skrip utilitas operasional, pemeliharaan server, pemburu kapasitas cloud, pemeriksaan kesehatan (*healthcheck*), dan pencadangan snapshot status.

---

## 📁 Daftar Skrip Operasional & Fungsinya

| Skrip | Penjelasan Fungsi (Bahasa Awam) |
| :--- | :--- |
| [`sg2_external_watchdog.py`](./sg2_external_watchdog.py) | **Pengawas Eksternal SG2**: Berjalan di node standby (SG2) untuk memantau kesehatan SG1 via SSH dan menarik backup mirror off-server tiap 2 jam. |
| [`singapore_batam_hunter.py`](./singapore_batam_hunter.py) | **Pemburu Kapasitas Batam/Singapore**: Menjalankan probe otomatis 24/7 ke Oracle Cloud API untuk mengklaim instance ARM (4 OCPU / 24GB) saat kapasitas tersedia. |
| [`healthcheck.py`](./healthcheck.py) | **Dokter Kesehatan Lengkap**: Memeriksa status systemd, dependensi library, koneksi database, dan kesehatan model AI. |
| [`council_watchdog.py`](./council_watchdog.py) | **Watchdog Internal SG1**: Memantau kesehatan `kibot-master.service` dan socket UDP 9991 dari dalam SG1. |
| [`backup_state_snapshot.py`](./backup_state_snapshot.py) | **Pencadangan State Cepat**: Membuat arsip terkompresi dari seluruh database `state/` saat ini. |
| [`cleanup_equity_corruption.py`](./cleanup_equity_corruption.py) | **Pembersih Anomali Ekuitas**: Mendeteksi dan memperbaiki inkonsistensi saldo bila terjadi lonjakan/penurunan palsu akibat kegagalan sinkronisasi API. |
| [`soak_report.py`](./soak_report.py) | **Laporan Uji Ketahanan (Soak Test)**: Mengumpulkan metrik stabilitas sistem setelah berjalan berhari-hari tanpa henti. |
| [`snapshot_runtime.sh`](./snapshot_runtime.sh) | **Snapshot Kondisi Runtime**: Menyimpan cuplikan proses Linux, port, dan penggunaan RAM untuk investigasi. |
| [`rollback.py`](./rollback.py) | **Pemulih Cadangan (Rollback)**: Mengembalikan kondisi state sistem ke snapshot cadangan sebelumnya jika terjadi error fatal. |
| [`scan_secrets.py`](./scan_secrets.py) | **Pemindai Kebocoran Kunci**: Memeriksa seluruh file sebelum di-commit agar tidak ada API key atau rahasia yang lolos ke Git. |

---

## 📂 Subdirektori Khusus
- [`archive/`](./archive/README.md) — Arsip skrip audit dan pengujian masa lalu yang sudah dipensiunkan.
- [`diagnostics/`](./diagnostics/README.md) — Skrip investigasi forensik mendalam saat terjadi anomali data.
- [`research/`](./research/README.md) — Skrip riset kuantitatif, kalibrasi backtest, dan investigasi ground-truth sinyal.
