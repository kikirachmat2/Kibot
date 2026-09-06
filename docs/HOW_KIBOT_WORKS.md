# 📖 Panduan Lengkap: Cara Kerja KiBot Sovereign & Ekspektasi Realistis

Dokumen ini menjelaskan arsitektur *end-to-end* KiBot dari pemindaian pasar hingga realisasi laba/rugi, serta memberikan **gambaran jujur tanpa ilusi** mengenai risiko trading algoritmik, batas perlindungan modal, dan ekspektasi *passive income*.

Dokumen ini dirancang sebagai **rujukan utama operator manusia** dalam mengoperasikan, mengawasi, dan memahami keputusan otonom bot di server produksi.

---

## 1. Arsitektur Berdaulat (Sovereign Operating Principles)

KiBot tidak beroperasi seperti bot grid atau martingale konvensional yang sembarangan membeli saat harga turun tanpa batas. KiBot mengadopsi prinsip **Zero-Trust Multi-Tier Architecture**:

* **Capital Preservation First, Profit Second:** Lebih baik kehilangan peluang profit (*opportunity loss*) daripada kehilangan modal pokok (*capital drawdown*). Menolak transaksi di pasar buruk adalah tindakan investasi aktif.
* **Autonomous Council, Sovereign Control:** Bot mengambil keputusan analisis secara mandiri lewat dewan agen kuantitatif (*Council*), namun kendali modal tertinggi dan izin eksekusi tetap berada di tangan operator manusia.
* **Live Trading Gate (Gembok Eksekusi Nyata):** Tidak ada satu pun transaksi riil di bursa yang dapat dieksekusi sebelum variabel lingkungan `KIBOT_LIVE_TRADING_ENABLED=true` atau `KIBOT_TRADING_MODE=live` disetel secara sadar oleh operator (ditegaskan dalam [`Core/Support/ki_config.py`](../Core/Support/ki_config.py#L105)). Secara *default*, sistem berjalan dalam mode aman (fail-closed).
* **Single Source of Truth (SSOT):** Parameter risiko dan biaya transaksi dipusatkan di [`Core/Support/ki_config.py`](../Core/Support/ki_config.py), sedangkan status kepemilikan dompet dan posisi aktif dipusatkan di ledger rekonsiliasi [`state/live_truth.json`](../state/live_truth.json).

---

## 2. Alur Transaksi End-to-End (The 6-Stage Pipeline)

```
[ PASAR 24/7 ] (Indodax & Binance Data Feed)
      │
      ▼
┌──────────────────┐
│  1. SCANNER      │  Memindai order book & ticker pasar spot (Lead-Lag, Momentum, OBI)
└─────────┬────────┘
          ▼ (Kandidat Lolos Saringan Volume & Spread)
┌──────────────────┐
│  2. COUNCIL      │  Multi-analis kuantitatif (Z-score, Bayesian EV, Microstructure)
└─────────┬────────┘
          ▼ (Sinyal Mandat: APPROVED / ENTER)
┌──────────────────┐
│ 3. CAPITAL       │  Pengaman Modal Mutlak (Daily Loss Cap -3.0%, Churn Guard, Freshness 90s)
│    GOVERNOR      │  ──▶ JIKA GAGAL: FAIL-CLOSED (Order Ditolak Seketika)
└─────────┬────────┘
          ▼ (Izin Alokasi Modal Diberikan)
┌──────────────────┐
│  4. EXECUTOR     │  Idempotency check, Slippage-aware sizing, Limit Order HMAC-SHA512
└─────────┬────────┘
          ▼ (Order Terisi / Filled di Bursa)
┌──────────────────┐
│  5. ACCOUNTING   │  Round-Trip Ledger, Pemotongan Fee Riil (0.61%), Rekonsiliasi Live Truth
└─────────┬────────┘
          ▼ (Posisi Aktif Dikawal)
┌──────────────────┐
│  6. EXIT LOGIC   │  Take Profit (TP), Stop Loss (SL), Timeout / Deadline, Trailing Stop
└──────────────────┘
```

---

### Tahap 1: Scanner (Market Radar 24/7)
* Berjalan terus-menerus mengamati pasangan aset kripto di Indodax (pasar eksekusi) dan Binance (pasar acuan global).
* **Lead-Lag Alpha:** Mendeteksi pergerakan harga di bursa global berlikuiditas tinggi (Binance) yang belum sepenuhnya direspons oleh antrean di bursa lokal (Indodax).
* **Brutal Momentum & Order Book Imbalance (OBI):** Mengukur lonjakan volume beli mendadak serta rasio ketidakseimbangan bid/ask dalam antrean buku order.
* Pasangan koin yang lolos ambang batas likuiditas minimum (menghindari koin mati/tidak likuid) diteruskan ke tahap berikutnya sebagai *Candidate Pool*.

---

### Tahap 2: Council (Autonomous Decision Matrix)
* Terdiri dari analis kuantitatif algoritmik independen:
  * **Momentum Analyst:** Mengonfirmasi kekuatan dan arah tren pergerakan harga jangka pendek.
  * **Microstructure Analyst:** Memeriksa ketebalan bid/ask, spread harga beli-jual, dan risiko *slippage*.
  * **Valuation & Bayesian EV Gate:** Menghitung nilai harapan matematis (*Expected Value* berbasis probabilitas posterior Bayesian). Sinyal wajib memiliki probabilitas kemenangan minimum `MIN_SIGNAL_PROBABILITY = 0.65` (65%) untuk dipertimbangkan.
* Dewan mengeluarkan keputusan: `APPROVED` (layak beli), `WAIT` (kondisi pasar belum aman/optimal), atau `REJECTED`.
* Jika keyakinan matematis tidak melampaui ambang batas aman, Council **wajib** mengeluarkan instruksi `WAIT`.

---

### Tahap 3: Capital Governor (Penjaga Gawang Modal Paling Ketat)
Sebelum order apapun dikirim ke bursa, [`Core/Treasury/capital_governor.py`](../Core/Treasury/capital_governor.py) memeriksa serangkaian gerbang deterministik yang tidak bisa ditawar:
1. **Daily Loss Cap (-3.0%):** Dikonfigurasi lewat `MAX_DAILY_LOSS_PERCENT = 3.0` di [`Core/Support/ki_config.py`](../Core/Support/ki_config.py#L85). Jika total kerugian trading hari ini menyentuh 3.0% dari saldo awal hari ini (dengan batas lantai `MIN_EQUITY_FLOOR_IDR = 10,000`), sistem otomatis **LOCKED** dan menolak semua order baru hingga reset jam 00:00 WIB.
2. **Consecutive Loss & Daily Trade Caps:** Dibatasi maksimal 1 kerugian berturut-turut (`MAX_CONSECUTIVE_LOSSES = 1`) dan maksimal 4 transaksi per hari (`MAX_TRADES_PER_DAY = 4`) untuk mencegah *overtrading* dan *revenge trading*.
3. **Churn Guard:** Melarang pembelian berulang pada pasangan yang baru saja ditutup dalam rentang waktu singkat, guna menghindari pengikisan modal akibat akumulasi fee bursa.
4. **Data Freshness Guard:** Jika data ticker atau telemetri server lebih tua dari 90 detik, sistem langsung *fail-closed* (tolak order) demi menghindari pembelian buta di saat latensi jaringan tinggi.
5. **Execution Permissions:** Memverifikasi izin saldo kas IDR mencukupi di Indodax di atas batas pesanan minimum (Rp 10.000).

---

### Tahap 4: Executor (Eksekusi Pesanan Terukur)
* **Slippage-Aware Dynamic Sizing:** Ukuran modal pesanan dibatasi secara dinamis agar tidak melebihi ketebalan antrean orderbook, membatasi deviasi harga (*slippage default* ditargetkan di bawah `0.10%`).
* **Limit Order Execution:** Mengirimkan order jenis limit ke API privat Indodax menggunakan otentikasi terenkripsi HMAC-SHA512.
* **Pre-Flight Sanity Check:** Memverifikasi saldo kas riil terkini di bursa via API `getInfo` sebelum melepaskan signature pesanan.

---

### Tahap 5: Accounting & Single Source of Truth
* **Round-Trip Accounting:** Sebuah trade baru dianggap selesai jika order beli telah ditutup secara sempurna oleh order jual yang sesuai.
* **Fee Friction Riil (Sesuai Struktur Resmi Indodax):**
  * Biaya Taker IDR: **0.31% saat beli** dan **0.30% saat jual** (total beban bolak-balik: **0.61% round-trip**).
  * Biaya Maker IDR: **0.21% saat beli** dan **0.20% saat jual** (total beban bolak-balik: **0.41% round-trip**).
  * Semua perhitungan EV dan profit bersih memperhitungkan potongan fee riil ini sejak detik pertama trade dibuka.
* **Sinkronisasi Ledger:** Seluruh perubahan saldo kas dan nilai koin dicatat ke [`state/live_truth.json`](../state/live_truth.json) dan [`state/round_trip_accounting.json`](../state/round_trip_accounting.json).

---

### Tahap 6: Exit Logic (Keluar dari Pasar Tanpa Emosi)
Bot keluar dari posisi aktif secara otonom berdasarkan parameter objektif:
1. **Take Profit (TP):** Target standar `SCALPING_TP_PERCENT = 1.0%` di atas harga masuk (disesuaikan setelah menutup beban fee bursa).
2. **Stop Loss (SL):** Batas toleransi risiko `SCALPING_SL_PERCENT = 2.0%` di bawah harga masuk untuk memotong kerugian sebelum membesar.
3. **Deadline Pressure / Timeout:** Jika pergerakan harga mendatar (*sideways*) dan tidak kunjung menyentuh target dalam durasi waktu tertentu, posisi dilikuidasi untuk membebaskan modal yang mengendap.
4. **Dynamic Trailing Stop:** Menggeser batas pengaman naik saat harga bergerak positif untuk mengunci keuntungan mengambang.

---

## 3. Bedah Realitas & Ekspektasi Risiko: Kejujuran Tanpa Ilusi

> ⚠️ **PERINGATAN PENTING UNTUK INVESTOR & OPERATOR:**
> Trading kripto algoritmik **BUKAN** skema cepat kaya, **BUKAN** instrumen pendapatan pasif berbunga tetap, dan **BUKAN** mesin pencetak profit harian yang pasti. 
> Setiap modal yang dialokasikan memiliki risiko penurunan nilai (*drawdown*).

---

### A. Realitas Win Rate: Mengapa Win Rate Mentah Bisa Rendah?

* Dalam pengujian empiris strategi awal (*Tier-2* / sinyal tanpa filter ketat Council), data historis mencatat **win rate mentah berkisar ~26%**.
* **Penyebab Utama Rendahnya Win Rate Mentah di Pasar Spot:**
  1. **Beban Biaya Transaksi (Fee Friction):** Dengan total biaya *taker round-trip* sebesar **0.61%** (0.31% beli + 0.30% jual) ditambah estimasi *slippage* ~0.10%, setiap trade membutuhkan kenaikan harga minimal **~0.71% - 0.80% hanya untuk mencapai titik impas (breakeven)**. Pada transaksi scalping berfrekuensi tinggi, biaya transaksi ini mengikis laba tipis menjadi kerugian riil.
  2. **Derau Pasar Spot (Market Noise & Spoofing):** Pasar spot altcoin lokal rentan terhadap lonjakan spread mendadak dan antrean palsu (*spoofing*) yang kerap menyentuh titik stop loss sebelum tren sebenarnya terbentuk.

#### Status Terkini Filter Tier-1 (Council APPROVED):
* **Hasil Backtest Historis:** Penyaringan ketat melalui dewan analis (*Tier-1: Council APPROVED*) menghasilkan performa backtest yang jauh lebih unggul daripada Tier-2, dengan **win rate historis ~44%** dan nilai harapan matematis (*Expected Value*) yang positif.
* **Fakta Kritis (Jujur Tanpa Overclaiming):**
  * Angka win rate ~44% di atas adalah hasil **BACKTEST HISTORIS**, dan **BELUM TERVALIDASI** secara statistik pada data *forward-looking* di pasar nyata (*live out-of-sample*).
  * Sistem **BARU SAJA MULAI** mengumpulkan data validasi *forward-looking* ini secara transparan melalui modul *COUNCIL_APPROVED Shadow Tracking*.
  * Dibutuhkan sampel transaksi nyata yang memadai (**minimal N ≥ 30 hingga 50 transaksi selesai**) sebelum operator dapat secara ilmiah menyimpulkan bahwa Tier-1 terbukti tangguh dalam kondisi pasar terkini.
* **Ekspektasi Operator:**
  > *"Sistem ini SEDANG DALAM PROSES membuktikan dirinya sendiri di pasar nyata, BUKAN sistem yang sudah selesai atau terbukti sempurna."*
  Sikap ini adalah dasar manajemen risiko yang sehat: objektif, berbasis data empiris, dan tidak terbuai optimisme berlebihan.

---

### B. Ekspektasi Realistis Soal "Passive Income"

1. **Bot Tidak Menghasilkan Uang Setiap Hari:**
   Ada siklus hari atau bahkan minggu di mana volatilitas pasar tidak mendukung, bot mengalami rangkaian kerugian (*drawdown*), atau bot memilih bertahan dalam status `WAIT`.
2. **Status "WAIT" Adalah Perlindungan, Bukan Kerusakan:**
   Melihat bot berdiam diri selama 24–48 jam tanpa membuka posisi sering disalahartikan oleh pemula sebagai "bot error". Pada KiBot, diam adalah keputusan terencana: **menolak mempertaruhkan uang Anda pada pasar yang tidak memiliki keunggulan statistik (*no edge*)**.
3. **Prinsip Asimetri Risk-to-Reward:**
   Sistem dengan win rate 40–45% tetap dapat menghasilkan keuntungan bersih yang sehat asalkan rata-rata laba saat menang (*average win*) secara konsisten lebih besar daripada rata-rata rugi saat kalah (*average loss*), dipadukan dengan disiplin *cut-loss* yang kaku.
4. **Pentingnya Memahami Batas Risiko Harian (Daily Loss Cap -3.0%):**
   * Capital Governor membatasi kerugian harian maksimal sebesar **-3.0%** dari saldo awal hari berjalan.
   * **Catatan Kritis bagi Operator:** Karena batas harian mereset patokan saldonya setiap tengah malam (00:00 WIB), jika terjadi hari buruk berturut-turut tanpa adanya rem kumulatif (*overall drawdown circuit breaker*), modal dapat menyusut secara bertahap. Jangan pernah menggunakan dana darurat, uang kebutuhan pokok, atau dana pinjaman untuk trading.
5. **Risiko Eksternal yang Berada di Luar Kontrol Algoritma:**
   Gangguan koneksi API bursa Indodax, penangguhan penarikan/deposit koin oleh bursa (*wallet maintenance*), delisting mendadak pasangan aset, atau likuiditas pasar yang mendadak kering adalah risiko sistemik bursa yang tidak dapat dieliminasi 100% oleh kode manapun.

---

## 4. Panduan Operator: Apa yang Harus Dilakukan Jika Terjadi Masalah?

| Gejala / Kondisi | Arti Sistem | Tindakan Operator |
| :--- | :--- | :--- |
| **Status `WAIT` berlangsung lama (> 24 jam)** | Kondisi pasar belum aman atau tidak ada koin dengan EV positif. | **Biarkan bot bekerja.** Jangan paksa open posisi manual. Cek tab Scanner/Council di dashboard untuk melihat alasan penolakan kandidat. |
| **Status `LOCKED` / `global_daily_loss_cap_breached`** | Kerugian hari ini telah menyentuh batas proteksi **-3.0%**. | Sistem mengunci diri secara otomatis demi menyelamatkan sisa modal 97%. Sistem akan otomatis mengevaluasi ulang setelah pergantian hari (00:00 WIB). |
| **Status `STALE_DATA_HEARTBEAT` (> 90s)** | Telemetri scanner atau koneksi pasar mengalami kelambatan/putus. | Jalankan `bin/kibotctl doctor` di server SG1 untuk memeriksa kesehatan service scanner. |
| **Status `ERROR` pada Dashboard** | Terdapat kendala internal pada salah satu daemon systemd. | Jalankan `bin/kibotctl status` dan periksa log terkait dengan `journalctl -u kibot-master -n 50`. |

---

*Dokumen ini diperbarui secara berkala seiring berjalannya validasi forward-looking Tier-1 dan penyempurnaan parameter risiko sovereign.*
