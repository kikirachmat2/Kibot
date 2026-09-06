# ⚡ Core/Executors — Tangan Pelaksana Transaksi Pasar

Folder ini bertindak sebagai **Tangan Pelaksana (Executor Layer)** KiBot. Tugas utamanya adalah menerima mandat order yang sudah lolos seleksi dari Council dan mengeksekusi order riil di bursa secara presisi, cepat, dan aman.

> [!IMPORTANT]
> **Status Risiko**: **SANGAT TINGGI (High-Risk Runtime)**.
> File di dalam folder ini terhubung langsung dengan uang riil dan service systemd `kibot-executor.service`. Dilarang mengubah struktur, memindahkan, atau me-rename file di folder ini tanpa prosedur pengujian menyeluruh.

---

## 📁 Daftar File & Subdirektori

| File / Folder | Penjelasan Fungsi (Bahasa Awam) |
| :--- | :--- |
| [`Indodax/indodax_executor.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Executors/Indodax/indodax_executor.py) | **Pelaksana Order Indodax**: Mendengarkan antrean mandat trading dari Council, mengecek ketersediaan saldo dan spread order book, mengirim order beli/jual ke Indodax API, mengawasi status fill (eksekusi), dan mengelola Take Profit / Stop Loss. |

---

## 🛡️ Aturan Operasional Pelaksana (Execution Rules)
1. **Pintu Gerbang Berlapis**: Order beli HANYA dikirim jika Scanner, Council AI, Expected Value, Pre-trade Simulator, Risk Gate, dan Saldo Indodax semuanya lolos 100%.
2. **Perhitungan Fee & Likuiditas**: Entry posisi wajib memastikan koin memiliki kedalaman order book (*depth*) yang cukup agar nantinya bisa dijual kembali tanpa kerugian akibat *slippage* atau potongan fee bursa.
3. **Pembersihan Order Menggantung**: Order beli yang tidak terisi dalam jangka waktu tertentu (*stale*) otomatis dibatalkan, bukan dibiarkan mengejar harga pasar yang sudah lari.
4. **Indodax-Only**: Sistem ini murni didedikasikan untuk spot trading di Indodax. Tidak ada eksekutor wallet eksternal, DeFi, atau chain bridge.
