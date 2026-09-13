# KiBot V2 — Formal Known Gaps & Risk Register

Dokumen ini mencatat secara formal 3 kelemahan/gap kritis arsitektur yang teridentifikasi dalam audit self-critical, namun **belum diimplementasikan solusinya pada Fase 1**. Status seluruh item di bawah adalah **BELUM DITANGANI**, dan wajib diselesaikan sebelum live trading dengan uang riil (Fase 3/4) diaktifkan.

---

## Ringkasan Risk Register

| Risk ID | Deskripsi Gap | Tingkat Risiko | Dampak Potensial | Target Penyelesaian | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **GAP-01** | Partial Fill & Liquidity Exhaustion | **HIGH** | Modal tersangkut, orderbook tipis tereksekusi di harga buruk | Fase 2 (Execution Engine) | **BELUM DITANGANI** |
| **GAP-02** | Cloudflare / 502 Bad Gateway Handling | **HIGH** | Bot buta sesaat, order state menggantung (in-flight limbo) | Fase 2 (REST Gateway) | **BELUM DITANGANI** |
| **GAP-03** | State Discrepancy Ekstrem saat Boot Reconciliation | **CRITICAL** | Posisi hantu (ghost positions), double open, overleveraged | Fase 2 (Reconciliation Engine) | **BELUM DITANGANI** |
| **GAP-04** | Heuristic Win-Probability Weights without per-symbol statistical calibration | **MEDIUM** | Formula estimasi probabilitas belum membaca historical track record riil per koin | Fase 2 (Strategy Stats Port) | **BELUM DITANGANI** |

---

## 1. GAP-01: Partial Fill & Liquidity Exhaustion

- **Status**: **BELUM DITANGANI**
- **Severity**: HIGH
- **Komponen Terdampak**: `KiBot V2/executor/order_router.py`, `KiBot V2/executor/position_manager.py`

### Deskripsi Masalah
Pada paper trading, order dieksekusi dengan asumsi *instant 100% full fill*. Namun di bursa riil (Indodax):
1. **Orderbook Tipis**: Sinyal buy sebesar Rp 5.000.000 pada koin berlikuiditas rendah mungkin hanya terisi Rp 750.000 (15%), sementara sisanya (Rp 4.250.000) menggantung di orderbook sebagai open limit order.
2. **Liquidity Exhaustion / Slippage**: Jika order dipaksakan menggunakan market taker, harga rata-rata eksekusi (VWAP) bisa melonjak jauh melampaui entry price yang dievaluasi Council, mengubah trade dari positive Expected Value (+EV) menjadi guaranteed negative EV (-EV).
3. **Ghost Positions**: Saat harga bergerak naik setelah partial fill, sisa open order tidak pernah terisi. Sistem saat ini belum memiliki mekanisme:
   - Timeout auto-cancellation untuk sisa order yang belum terisi (e.g. cancel unfill after 30 seconds).
   - Recalculation stop-loss dan take-profit berdasarkan *actual filled volume* bukan *intended volume*.

### Mitigasi yang Direncanakan (Fase 2)
- Implementasi Order State Machine: `PENDING_SUBMIT` -> `SUBMITTED` -> `PARTIALLY_FILLED` -> `FILLED` / `CANCELLED`.
- Dynamic Order Sizing berbasis L2 depth: Alokasi order dibatasi maksimal 10% dari kedalaman orderbook pada 3 tick teratas.
- Auto-Cancel Sisa Partial Fill: Jika dalam 20 detik sisa order tidak terisi, kirim perintah cancel REST ke exchange, lalu daftarkan porsi yang sudah terisi ke `PositionManager` dengan ukuran riil.

---

## 2. GAP-02: Cloudflare & 502 Bad Gateway Handling

- **Status**: **BELUM DITANGANI**
- **Severity**: HIGH
- **Komponen Terdampak**: `KiBot V2/ingestion/indodax_ws.py`, REST fallback di `enrichment/`, order submit REST di `executor/`

### Deskripsi Masalah
Bursa Indodax kerap mengalami lonjakan trafik saat volatilitas pasar tinggi, memicu proteksi Cloudflare (HTTP 502 Bad Gateway, 504 Gateway Timeout, atau Cloudflare Turnstile/Challenge HTML page):
1. **In-Flight Limbo**: Jika bot mengirim perintah order `POST /trade/buy` dan menerima respons `502 Bad Gateway`, bot **TIDAK DAPAT MEMASTIKAN** apakah order tersebut:
   - Gagal sampai ke matching engine bursa (order TIDAK terpasang), ATAU
   - Sukses dieksekusi oleh matching engine, tetapi HTTP connection putus saat bursa mengirim kembali respons ke bot (order SUDAH terpasang).
2. **Bahaya Blind Retry**: Jika bot menganggap 502 = gagal dan langsung mencoba order ulang (retry), bot akan membeli **DUA KALI LIPAT** dari modal yang diizinkan (Double Buy).
3. **HTML Response Poisoning**: Saat Cloudflare mencegat request, respons yang dikembalikan berupa teks HTML `<!DOCTYPE html>...` bukan JSON. Jika parser mencoba `resp.json()`, sistem akan crash dengan `JSONDecodeError`.

### Mitigasi yang Direncanakan (Fase 2)
- Idempotent Client Order ID (`client_order_id`): Setiap order diberi UUID unik dari bot.
- Status Verification Loop on 5xx: Jika order submit mengembalikan status 500/502/504 atau timeout:
  - JANGAN langsung retry order baru.
  - Masukkan order ke state `UNKNOWN_PENDING_QUERY`.
  - Lakukan polling ke endpoint `open_orders` dan `order_history` untuk memverifikasi apakah `client_order_id` tersebut tercatat di bursa sebelum mengambil keputusan lebih lanjut.
- Circuit breaker HTTP: Jika 3 request REST berturut-turut menerima HTTP 502/504, aktifkan cooldown darurat selama 60 detik dan hentikan sementara pengambilan posisi baru.

---

## 3. GAP-03: State Discrepancy Ekstrem saat Boot Reconciliation

- **Status**: **BELUM DITANGANI**
- **Severity**: CRITICAL
- **Komponen Terdampak**: `KiBot V2/storage/state_reconciler.py`, `KiBot V2/executor/position_manager.py`

### Deskripsi Masalah
Saat bot crash atau di-restart di server, `NonRecursiveStateReconciler` membaca state lokal dari disk (`durable_state.json`) dan membandingkannya dengan saldo serta open orders dari API bursa:
1. **External Manual Intervention**: Operator manusia mungkin telah menjual koin secara manual via website Indodax saat bot offline, atau memasang order stop-loss darurat di bursa.
2. **Liquidasi / Delisting**: Koin yang dipegang bot mengalami delisting atau saldo terpotong biaya storage.
3. **Discrepancy Ekstrem**:
   - Bot mencatat memiliki posisi terbuka 1.0 BTC, tetapi saldo bursa hanya menunjukkan 0.0 BTC.
   - Bot mencatat tidak ada posisi, tetapi saldo bursa memiliki koin senilai Rp 50.000.000 yang sedang floating loss.
4. **Resiko Saat Ini**: Logika rekonsiliasi Fase 1 hanya memulihkan status dasar tanpa memiliki *Conflict Resolution Policy* yang ketat. Jika terjadi perbedaan ekstrem, bot berisiko terus mencoba memantau posisi hantu (ghost position) yang sudah tidak ada di bursa, atau gagal mengelola risiko koin yang sebenarnya ada di akun.

### Mitigasi yang Direncanakan (Fase 2)
- Exchange-as-Single-Source-of-Truth Policy: Jika ada selisih antara state lokal dan saldo bursa saat boot:
  - Jika saldo bursa < posisi lokal: Catat posisi sebagai `FORCE_CLOSED_EXTERNALLY`, jangan pernah kirim sell order untuk saldo yang tidak ada.
  - Jika saldo bursa > posisi lokal (ada aset tak dikenal): Masukkan ke `UNMANAGED_EXTERNAL_ASSETS`, kirim alert telegram/email ke operator, dan JANGAN sembarangan menjual aset tersebut tanpa izin eksplisit.
- Boot-Safe Lock: Bot menolak membuka trade baru selama rekonsiliasi awal belum selesai dengan status `CLEAN` atau `MANUALLY_ACKNOWLEDGED`.

---

## 4. GAP-04: Heuristic Win-Probability Weights without Per-Symbol Statistical Calibration

- **Status**: **BELUM DITANGANI**
- **Severity**: MEDIUM
- **Komponen Terdampak**: `KiBot V2/council/evaluator.py`

### Deskripsi Masalah
Meskipun baseline win rate telah dikalibrasi ke `0.35` (berdasarkan rata-rata varian APPROVED V1), formula penyesuaian probabilitas saat ini masih mengandalkan bobot heuristik statis:
- Bonus `+0.10` jika `volume_ratio >= 1.5`
- Bonus `+0.08` jika `leadlag_score > 0.3` (atau penalti `-0.15` jika `< -0.2`)
- Bonus `+0.08` / Penalti `-0.12` untuk sentimen LLM

Kelemahan pendekatan ini:
1. **Tidak Ada Pembedaan Karakter Koin**: Koin likuid seperti `BTC/IDR` (yang memiliki win rate historis 58.3%) diperlakukan dengan formula bobot yang identik dengan altcoin berkapitalisasi mikro (yang memiliki win rate historis 25.0%).
2. **Missing Historical Sample Gate**: Belum ada verifikasi jumlah sampel minimum (`historical_sample_size >= 20`) sebelum mengizinkan order, berbeda dengan V1 `expected_value.py` yang mewajibkan `MIN_SAMPLE_SIZE`.

### Mitigasi yang Direncanakan (Fase 2)
- Porting penuh modul `strategy_stats.py` dari V1 ke arsitektur non-blocking / SQLite lokal.
- Evaluator membaca tabel win rate dan average win/loss aktual yang dikelompokkan secara spesifik per-simbol (`symbol_stats[symbol]`).
- Jika suatu pasangan koin memiliki riwayat trade <20 sampel, otomatis gunakan conservative fallback rate atau tolak masuk hingga sampel memadai.

---

## 5. CATATAN KOREKSI: Structural Gate Lockout Bug pada R:R Filter

- **Status**: **RESOLVED (Interim Modeling Implemented)**
- **Severity**: HIGH
- **Komponen Terdampak**: `KiBot V2/council/evaluator.py`, `KiBot V2/main.py`

### Deskripsi Masalah (Root Cause)
Setelah kalibrasi parameter empiris awal (`avg_win_pct = 2.8%`, `avg_loss_pct = 2.4%`), terjadi **Structural Lockout** di mana 100% sinyal pasar ditolak secara statis.
- **Penyebab**: Scanner `main.py` belum mengirimkan target keuntungan/kerugian spesifik per kandidat.
- Akibatnya, evaluator selalu menggunakan nilai default global 2.8% win dan 2.4% loss untuk seluruh pasangan.
- Setelah dikurangi biaya komisi roundtrip (0.42%) dan slippage (0.1%), rasio net reward-to-risk konstan bernilai $0.0228 / 0.0292 = 0.78$.
- Karena 0.78 selalu di bawah batas keamanan `MIN_RR_RATIO = 1.40`, gate R:R memblokir 100% kandidat tanpa memandang kualitas sinyal atau momentum pasar.

### Solusi yang Diterapkan (Fase 1 Interim)
1. **Semi-Dynamic TP/SL Modeling**: Evaluator kini menghitung target Take Profit dan Stop Loss semi-dinamis berdasarkan metrik kandidat aktual:
   - Target Take Profit dinaikkan secara asimetris pada koin dengan dorongan `leadlag_score > 0`, lonjakan volume (`volume_ratio > 1.0`), sentimen bullish, dan rentang volatilitas 24 jam.
   - Target Stop Loss disesuaikan dengan `spread_pct` untuk mencegah wick tick-traps.
2. **Karakterisasi Pasar di Ingestion/Main**: Sinyal kini membawa metrik likuiditas nyata (spread ketat 0.1% pada koin bervolume tinggi vs 0.8% pada koin illiquid, serta breakout score dekat 24h high).
3. **Hasil**: Sinyal berkualitas tinggi dengan momentum kuat kini mampu mencapai target $R:R \ge 1.40$ dan $EV \ge 0.30\%$, sementara sinyal lemah atau berspread lebar tetap tertolak secara wajar. Sinyal yang lolos membawa `target_tp_pct` dan `target_sl_pct` dinamis ke VirtualLedger.
4. **Target Permanen**: Solusi permanen tetap berupa porting penuh `strategy_stats.py` per-simbol (GAP-04).
