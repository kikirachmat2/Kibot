# 🛡️ KIBOT V2: GO-LIVE CHECKLIST & READINESS PROTOCOL

**Status Dokumen**: AUTOMATED READ-ONLY EVALUATION (Ported from V1 `live_readiness.py`)  
**Evaluator Engine**: [`storage.live_readiness.LiveReadinessEvaluator`](file:///Users/kiki/Documents/Web%20Develop/KiBot/KiBot%20V2/storage/live_readiness.py)  

> [!CAUTION]
> **ATURAN MUTLAK KEAMANAN (READ-ONLY GATEWAY):**
> Status yang dihasilkan oleh evaluator otomatis (`BELUM_SIAP` atau `SIAP_SOFT_LAUNCH`) bersifat **100% INFORMATIF & READ-ONLY**.
> Evaluator **DILARANG KERAS DAN TIDAK PERNAH** mengubah flag `LIVE_TRADING_ENABLED` secara otomatis.
> Perubahan flag `LIVE_TRADING_ENABLED` dari `false` ke `true` mutlak wajib dilakukan secara manual oleh operator setelah review komprehensif bersama Director.

---

## 🤖 Otomasi Evaluasi Kesiapan (5 Kriteria Kuantitatif V1)

Evaluator otomatis membaca riwayat trade tertutup dari `VirtualLedger` (`trade_history`) secara real-time setiap kali posisi ditutup, memvalidasi 5 kriteria canonical:

| # | Kriteria Evaluasi | Target Threshold | Logika Pengujian | Status Dampak |
|---|---|---|---|---|
| **1** | **Sample Size (N)** | $\ge 30$ closed trades | Uji signifikansi statistik performa | Mencegah premature live dari small sample luck |
| **2** | **Profit Factor (PF)** | $\ge 1.50$ | Gross Profit / Gross Loss (net fee 0.21%) | Memastikan reward jauh melampaui drag biaya transaksi |
| **3** | **Net Win Rate (WR)** | $\ge 45.0\%$ | Realized wins / Total trades | Memastikan akurasi sinyal di atas baseline acak |
| **4** | **Max Drawdown (MDD)** | $\le 6.0\%$ | $(Peak - Equity) / Peak \times 100\%$ | Menguji daya tahan drawdown di bawah risk cap |
| **5** | **Time Diversity** | $\ge 10$ hari kalender | Tanggal unik WIB pada closed trades | Menguji performa di multi-regime (bukan 1 hari tren) |

---

## 🚦 Status Verdict & Tahapan Transisi

Sistem mengklasifikasikan kesiapan ke dalam 2 tingkatan status:

1. **🔴 BELUM_SIAP**
   - Terjadi jika salah satu atau lebih dari 5 kriteria belum terpenuhi.
   - Tindakan: Sistem tetap berjalan dalam mode Paper Virtual Ledger. Live trading ditolak keras.

2. **🟡 SIAP_SOFT_LAUNCH (Bukan Langsung Full Live)**
   - Terbuka hanya jika seluruh 5 kriteria terpenuhi serentak ($\ge 30$ trades, PF $\ge 1.5$, WR $\ge 45\%$, MDD $\le 6\%$, $\ge 10$ hari).
   - **Protokol Fase 1 (Modal Mikro):**
     * Alokasi modal mikro riil: **Rp 50.000 – Rp 100.000** per posisi.
     * Tujuan: Mengukur slippage aktual Indodax, maker/taker queue fill rate, dan perilaku orderbook riil tanpa risiko modal signifikan.
     * Evaluasi ulang setelah 50 trade di Fase 1 sebelum pertimbangan ekspansi ukuran modal.

---

## 🎯 Notifikasi Milestone & Transisi Status (Telegram)

Evaluator terhubung langsung ke [`TelegramNotifier`](file:///Users/kiki/Documents/Web%20Develop/KiBot/KiBot%20V2/notifications/telegram_notifier.py) (asynchronous, non-blocking 0ms hot-path impact):
- **Milestone Alert**: Terkirim otomatis saat paper trade mencapai **10, 20, 30, dan 50 closed trades**.
- **Status Change Alert**: Terkirim otomatis saat status berubah (misal: `BELUM_SIAP` $\rightarrow$ `SIAP_SOFT_LAUNCH`).
- **Risk Gate Trip Alerts**: Terkirim saat Circuit Breaker (18% DD) atau Daily Loss Cap (3%) terpicu.
- **System Alerts**: Terkirim saat WebSocket disconnect gagal reconnect setelah backoff maksimal (30s) atau saat proses crash.

---

## ✍️ PROTOKOL PENGESAHAN MANUAL OPERATOR

Ketika status mencapai `SIAP_SOFT_LAUNCH`, langkah yang WAJIB dilakukan sebelum mengubah setting:
1. Jalankan audit trade report: `python3 -m storage.live_readiness`
2. Ekspor ringkasan performa paper ledger ke log terverifikasi.
3. Review bersama Director untuk persetujuan alokasi modal mikro (Rp 50.000 - Rp 100.000).
4. Operator secara sadar mengubah `LIVE_TRADING_ENABLED = true` di environment / config.

