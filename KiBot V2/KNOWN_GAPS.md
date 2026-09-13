# KiBot V2 — Formal Known Gaps & Risk Register

Dokumen ini mencatat secara formal 3 kelemahan/gap kritis arsitektur yang teridentifikasi dalam audit self-critical, namun **belum diimplementasikan solusinya pada Fase 1**. Status seluruh item di bawah adalah **BELUM DITANGANI**, dan wajib diselesaikan sebelum live trading dengan uang riil (Fase 3/4) diaktifkan.

---

## Ringkasan Risk Register

| Risk ID | Deskripsi Gap | Tingkat Risiko | Dampak Potensial | Target Penyelesaian | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **GAP-01** | Partial Fill & Liquidity Exhaustion | **HIGH** | Modal tersangkut, orderbook tipis tereksekusi di harga buruk | Fase 2 (Execution Engine) | **BELUM DITANGANI** |
| **GAP-02** | Cloudflare / 502 Bad Gateway Handling | **HIGH** | Bot buta sesaat, order state menggantung (in-flight limbo) | Fase 2 (REST Gateway) | **BELUM DITANGANI** |
| **GAP-03** | State Discrepancy Ekstrem saat Boot Reconciliation | **CRITICAL** | Posisi hantu (ghost positions), double open, overleveraged | Fase 2 (Reconciliation Engine) | **BELUM DITANGANI** |

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
