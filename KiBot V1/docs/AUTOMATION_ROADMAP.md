# KiBot Automation Roadmap: Peta Otomatisasi & Batasan Permanen

Dokumen ini adalah **piagam rujukan permanen** yang mendefinisikan batas tegas antara apa yang **sepenuhnya diotomatisasi oleh mesin** dan apa yang **HARUS selalu berada di bawah kendali keputusan manusia (operator)**.

Filosofi utama KiBot adalah:  
> *"Mesin mengeksekusi disiplin teknis dan pemulihan operasional secepat kilat tanpa lelah, namun manusia memegang kedaulatan mutlak atas modal, toleransi risiko, dan strategi."*

---

## Ringkasan Matriks Pembagian Otoritas

| Area Fungsional | Dikelola Mesin (Otomatis) | Wajib Keputusan Operator (Manual) | Alasan Filosofis & Keamanan |
|---|---|---|---|
| **Kesehatan Service & Uptime** | ✅ Restart otomatis, watchdog self-healing | ❌ Tidak perlu campur tangan | Mesin harus pulih secepat mungkin saat crash tanpa menunggu bangunnya operator. |
| **Penanganan Insiden Jaringan/API** | ✅ Anti-flapping, eskalasi log/alert | ❌ Tidak perlu campur tangan | Mencegah kepanikan operator terhadap noise koneksi sesaat. |
| **Audit Kesiapan Live (Readiness)** | ✅ Hitung 5 kriteria & kirim milestone alert | ❌ Evaluasi metrik kuantitatif | Menghilangkan bias psikologis "merasa sistem sudah siap". |
| **Laporan Kinerja Berkala** | ✅ Daily report ringkas jam 06:00 WIB | ❌ Tidak perlu ketik manual | Transparansi harian pasif bagi operator. |
| **Circuit Breaker Modal (Max Drawdown)**| ❌ **DILARANG OTOMATIS** | ✅ Kunci dibuka HANYA via `kibotctl drawdown-ack` | Jika terjadi loss beruntun atau anomali market, mesin tidak boleh berjudi membuka kunci sendiri. |
| **Aktivasi Live / Alokasi Modal Riil** | ❌ **DILARANG OTOMATIS** | ✅ Keputusan manual isi modal & set flag live | Paper trading berbeda dari uang riil (slippage & psikologi operator). |
| **Transisi Soft Launch ke Full Live** | ❌ **DILARANG OTOMATIS** | ✅ Review manual performa 15-20 live trades | Validasi eksekusi riil wajib ditinjau manusia sebelum modal dibesarkan. |
| **Parameter Strategi (TP/SL/Confidence)**| ❌ **DILARANG OTOMATIS** | ✅ Review & approval perubahan rule | Mencegah model AI mengalami over-fitting liar tanpa pengawasan. |

---

## KATEGORI A: Otomatisasi Operasional (Sudah Aktif & Berjalan)

Area-area berikut sepenuhnya dijalankan oleh algoritma runtime tanpa membutuhkan intervensi manual sehari-hari:

### 1. Self-Healing System Services
- **Systemd Supervision**: Seluruh daemon core (`kibot-scanner`, `kibot-master`, `kibot-executor`, `kibot-dashboard`) dikonfigurasi dengan `Restart=always` dan `RestartSec=5s`. Jika terjadi *unhandled exception* atau memori habis, sistem operasi langsung menghidupkan ulang proses secara instan.
- **Council Watchdog Internal**: Daemon mendeteksi jika loop evaluasi macet (*heartbeat stall*) dan me-restart thread yang bermasalah.
- **SG2 External Watchdog**: Memeriksa respons API/port dari server luar. Jika host trading tidak responsif, watchdog mengirimkan alert independen ke Telegram.

### 2. Siklus Insiden Anti-Flapping & Escalation Ladder
- **Anti-Flapping Filter**: Fluktuasi koneksi API publik (misal Indodax 502/timeout sesaat) diredam oleh algoritma debouncing. Sistem tidak membombardir operator dengan pesan kepanikan untuk anomali yang sembuh sendiri dalam 1–2 siklus.
- **Escalation Ladder**: Jika error bertahan lebih dari ambang batas toleransi (misal 5 menit tanpa recovery), insiden dinaikkan statusnya dari `WARNING` menjadi `CRITICAL` dan memicu notifikasi prioritas tinggi dengan instruksi mitigasi yang jelas.

### 3. Evaluasi Kesiapan Live (Live Readiness Scorecard)
- Mesin secara otonom memindai seluruh trade closed varian `APPROVED` dan menghitung 5 kriteria kuantitatif:
  1. Sample Size: $N \ge 30$
  2. Profit Factor: $PF \ge 1.50$
  3. Win Rate Net: $WR \ge 45\%$
  4. Max Drawdown: $MDD \le 6\%$
  5. Sebaran Hari: $\ge 10$ hari kalender berbeda
- **Zero-Spam Milestone Alert**: Sistem hanya mengirimkan notifikasi saat sampel menyentuh angka kritis ($N = 10, 20, 30$) atau saat kriteria berhasil beralih status.

### 4. Pelaporan Harian Ringkas (Telegram Daily Report)
- Mengirimkan rangkuman otomatis setiap pagi pukul 06:00 WIB.
- Didesain ringkas untuk konsumsi awam: saldo, status keamanan (🟢/🟡/🔴), PnL harian, dan alasan dinamis mengapa bot membeli atau menahan order hari itu.

---

## KATEGORI B: Batasan Mutlak Otoritas Manusia (Strict Human-in-the-Loop)

Area-area berikut **DILARANG KERAS diotomatisasi**. Sistem dirancang agar menolak melanjutkan aksi trading jika tidak ada persetujuan eksplisit dari operator manusia:

### 1. Pembukaan Kunci Circuit Breaker (`CapitalGovernor`)
- **Pemicu Otomatis**: Jika drawdown mencapai batas proteksi modal (misal overall drawdown $\ge 18\%$ atau daily loss $\ge 3\%$), `CapitalGovernor` secara otonom membanting rem darurat (*tripped*), menghentikan seluruh entry baru, dan mengunci sistem menjadi status `TERKUNCI` (🔴).
- **Aturan Permanen**: **Mesin tidak boleh membuka kuncinya sendiri**. Kunci HANYA dapat dibuka setelah operator manusia menginvestigasi penyebab kerugian dan mengetik perintah:
  ```bash
  bin/kibotctl drawdown-ack --reason "Analisis penyebab loss dan konfirmasi mitigasi"
  ```
- **Alasan**: Mencegah fenomena *gambler's fallacy* atau loop algoritma gila yang terus mencoba trading saat pasar sedang crash abnormal.

### 2. Keputusan Memulai Live Trading & Pengisian Modal
- Bot tidak akan pernah menempatkan order IDR nyata sebelum operator:
  1. Menyetor saldo ke akun Indodax secara sadar.
  2. Mengeset environment variable `KIBOT_LIVE_TRADING_ENABLED=true` atau `KIBOT_TRADING_MODE=live`.
- **Alasan**: Menjaga kedaulatan dompet operator dari segala bentuk kesalahan konfigurasi atau inisialisasi default.

### 3. Transisi dari Soft Launch ke Full Live Trading
- Begitu varian `APPROVED` lulus 5 kriteria, mesin **hanya boleh merekomendasikan** status `🟡 SIAP SOFT LAUNCH`.
- Mesin **DILARANG** menaikkan ukuran posisi secara otonom ke modal penuh.
- Operator wajib mendampingi 15–20 trade pada fase Soft Launch (posisi mikro Rp 50.000 – Rp 100.000) untuk memverifikasi eksekusi riil, slippage spread, dan biaya taker/maker aktual di pasar hidup. Keputusan menaikkan modal ke batas maksimum sepenuhnya di tangan operator.

### 4. Perubahan Strategi Kuantitatif & Ambang Batas Risiko
- Penyesuaian logika teknikal (indikator momentum, formula scoring Council, rasio Take-Profit / Stop-Loss) wajib melalui audit kode, penulisan unit test, dan persetujuan git commit oleh pengembang/operator.
- Modul AI atau learning script dilarang mengubah file strategi inti secara liar tanpa validasi regresi.

---

## Pedoman Pembaruan Dokumen

Setiap kali ada penambahan kapabilitas otomasi baru di masa mendatang, tanyakan dua pertanyaan uji kelayakan:
1. *"Jika fitur ini otomatis dan mengalami bug, apakah modal riil operator bisa lenyap dalam hitungan menit?"*  
   $\rightarrow$ Jika **YA**, fitur tersebut **WAJIB masuk Kategori B** (butuh persetujuan manusia).
2. *"Apakah tindakan ini murni pemeliharaan teknis / observability yang tidak menyentuh eksekusi saldo?"*  
   $\rightarrow$ Jika **YA**, fitur tersebut **AMAN masuk Kategori A** (otomatisasi operasional).
