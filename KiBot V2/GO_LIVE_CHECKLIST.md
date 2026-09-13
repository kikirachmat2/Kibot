# 🛡️ KIBOT V2: GO-LIVE CHECKLIST & PROTOCOL

**Status Dokumen**: DRAFT - PENDING OPERATOR & STAKEHOLDER REVIEW  
**Tujuan**: Menetapkan kerangka kriteria kuantitatif wajib yang harus dipenuhi dan diverifikasi bersama sebelum flag `LIVE_TRADING_ENABLED` diubah dari `false` menjadi `true`.

> [!CAUTION]
> **ATURAN MUTLAK:**
> DILARANG menyalakan `LIVE_TRADING_ENABLED=true` jika salah satu dari checklist kuantitatif di bawah ini belum berstatus **VERIFIED** dengan bukti rekaman data konkret. Angka target final di bawah ini akan disepakati bersama oleh operator.

---

## 📊 1. Stabilitas & Ketahanan Runtime (Stability Gate)
- [ ] **Stabilitas Berkelanjutan**: Sistem berjalan minimal **[N_HARI] hari berturut-turut** dalam mode paper trading tanpa pernah mengalami:
  * Crash proses (`SIGSEGV`, `OOM`, `uncaught exception`).
  * Socket hang / deadlock.
  * Memory leak (RAM stabil di bawah target budget).
- [ ] **Log & Resource Hygiene**:
  * Systemd journal terbukti tidak melebihi **[MAX_JOURNAL_MB] MB**.
  * Log aplikasi berputar (*rotated*) dengan benar tanpa penumpukan disk.
  * CPU Steal dari hypervisor terpantau aman (**< [MAX_STEAL_PCT]%**).

---

## ⚡ 2. Kualitas Ingestion & Concurrency (Data & Latency Gate)
- [ ] **Signal Drop Rate**:
  * Rasio sinyal terbuang (*dropped signals*) di bawah **< [TARGET_DROP_RATE_PCT]%** (Target desain V2: < 2.0%, batas toleransi < 5.0%).
  * Tidak ada pembekuan antrian simbol (*coalescing queue* bekerja optimal).
- [ ] **Council Deliberation Latency**:
  * Latensi keputusan rata-rata: **< [TARGET_LATENCY_AVG_MS] ms** (Target desain V2: < 150 ms).
  * Latensi p90: **< [TARGET_LATENCY_P90_MS] ms** (Target desain V2: < 800 ms).
  * Latensi worst-case: **< [TARGET_LATENCY_MAX_MS] ms** (Target desain V2: < 2.000 ms).
- [ ] **Market Data Freshness**:
  * Usia data (*data age*) saat keputusan diambil: rata-rata **< [MAX_DATA_AGE_MS] ms**.
  * Heartbeat WebSocket mendeteksi koneksi mati dalam **< 5 detik**.

---

## 📈 3. Kinerja Strategi & Profitabilitas (Paper Trade Readiness)
- [ ] **Jumlah Sampel Minimum**: Telah mengeksekusi minimal **[MIN_SAMPLE_TRADES] trade** tertutup dalam mode paper trading.
- [ ] **Profit Factor (PF)**: Konsisten mencapai **PF $\ge$ [TARGET_PROFIT_FACTOR]** (misal $\ge$ 1.50) pada periode evaluasi.
- [ ] **Net Win Rate (WR)**: Konsisten mencapai **WR $\ge$ [TARGET_WIN_RATE_PCT]%** (misal $\ge$ 45.0%).
- [ ] **Diversitas Rezim Pasar**: Trade tersebar di minimal **[MIN_CALENDAR_DAYS] hari kalender berbeda** mencakup kondisi pasar *bullish*, *bearish*, dan *choppy/sideways*.

---

## 🔒 4. Pengujian Safety Gate Terkonfirmasi (Safety Simulation)
- [ ] **Drawdown Circuit Breaker**:
  * Telah diuji memicu (*tripped*) dengan benar saat drawdown buatan mencapai **[DRAWDOWN_THRESHOLD_PCT]%** (18.0%).
  * Terbukti mengunci seluruh order beli baru secara otomatis hingga reset manual.
- [ ] **Daily Loss Cap**:
  * Telah diuji memicu (*locked*) saat kerugian harian mencapai **[DAILY_LOSS_CAP_PCT]%** (3.0%).
  * Terbukti melakukan rollover bersih pada pukul 00:00 WIB.
- [ ] **Idempotency Guard**:
  * Terbukti menolak order duplikat/kembar pada simbol yang sama dalam jendela waktu **[IDEMPOTENCY_WINDOW_SEC] detik**.
- [ ] **Startup Reconciliation**:
  * Terbukti mencocokkan saldo akun riil dan posisi lokal tanpa *recursion error* saat bot di-restart.

---

## ✍️ LEMBAR PENGESAHAN OPERATOR
Sebelum flag live diaktifkan:
* **Tanggal Audit Terakhir**: `____________________`
* **Nama Operator Peninjau**: `____________________`
* **Tanda Tangan / Konfirmasi**: `[ ] APPROVED FOR SOFT LAUNCH ONLY`
