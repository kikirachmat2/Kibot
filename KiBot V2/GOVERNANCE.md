# KIBOT V2 TRADING GOVERNANCE & RUNBOOK OPERASIONAL

Dokumen tata kelola resmi (*Governance Document*) yang mengikat seluruh personel operasional (Operator) dan pengambil keputusan strategis (Director) dalam pengelolaan bot perdagangan algorithmic **KiBot V2**.

---

## 1. KEBIJAKAN "2-MAN RULE" (GO-LIVE ENFORCEMENT)

Sesuai arsitektur keselamatan institusional, flag `LIVE_TRADING_ENABLED` di lingkungan produksi **DILARANG KERAS** diubah menjadi `true` oleh satu orang secara sepihak.

### Prosedur Wajib Perubahan Status ke Live:
1. **Prasyarat Formal**:
   * Seluruh 5 kriteria di `storage/live_readiness.py` berstatus **`SIAP_SOFT_LAUNCH`** (Sample Size $\ge 100$, Profit Factor $\ge 1.50$, Win Rate $\ge 45.0\%$, Max Drawdown $\le 18.0\%$, dan Sebaran Hari Kalender $\ge 7$ hari).
   * Seluruh test suite unit/integrasi lulus 100% di server SG1.
   * Tidak ada alert kritis tak terselesaikan pada sistem witness SG2 selama minimal 72 jam terakhir.
2. **Pemberian Persetujuan Ganda (Dual-Signoff)**:
   * **Operator**: Melakukan verifikasi runtime checklist, kecukupan saldo Indodax, validitas IP whitelist API Key, dan menandatangani tiket perubahan.
   * **Director**: Memeriksa metrik kesiapan, menandatangani keputusan tertulis, dan memberikan otorisasi final.
3. **Pemberlakuan Teknis**:
   * Flag diatur secara eksplisit di `/etc/systemd/system/kibot-v2-paper.service` (atau file service live terpisah `kibot-v2-live.service`).
   * Audit log mencatat timestamp aktivasi dan token hash persetujuan.

---

## 2. PROSEDUR KILL-SWITCH MANUAL (EMERGENCY SHUTDOWN)

Jika terdeteksi anomali parah (misal: order loop, drift rekonsiliasi tak wajar, lonjakan drawdown tidak terduga, atau anomali feed bursa), jalankan protokol 3-tingkat berikut secara berurutan:

### Tingkat 1: Hentikan Service Bot Seketika (< 5 Detik)
SSH ke server SG1 (`152.69.218.198` / Tailscale `100.105.139.21`):
```bash
sudo systemctl stop kibot-v2-paper.service
# Verifikasi proses benar-benar mati
systemctl is-active kibot-v2-paper.service
ps aux | grep main.py
```

### Tingkat 2: Cabut Izin Akses API Bursa di Indodax (< 2 Menit)
1. Login ke portal web Indodax ([indodax.com](https://indodax.com)).
2. Masuk ke menu **Trade API** / **Kelola Kunci API**.
3. Klik tombol **Hapus** atau uncheck izin **`Trade`** pada API Key aktif KiBot.
4. Ini memastikan tidak ada order baru yang dapat dieksekusi bursa meskipun service bot mencoba melakukan restart otomatis.

### Tingkat 3: Evaluasi & Likuidasi Posisi Terbuka (< 5 Menit)
1. Periksa posisi aset yang sedang terbuka di dashboard bursa Indodax.
2. Jika kondisi pasar normal: biarkan trailing stop bursa atau jual manual secara bertahap menggunakan limit order untuk menghindari slippage ekstrem.
3. Jika terjadi *market flash crash*: lakukan eksekusi market sell darurat untuk memotong risiko modal.

---

## 3. MATRIKS ESKALASI & RESPON INSIDEN

| Tingkat Keparahan | Event Pemicu | Respon Sistem Otomatis | Jalur Eskalasi & Waktu Tanggap |
| :--- | :--- | :--- | :--- |
| **P1 - CRITICAL** | • Circuit Breaker DD 18% trip<br>• Daily Loss Cap 3% trip<br>• Drift saldo bursa vs ledger > Rp 50.000<br>• Server SG1 down > 3 menit (Witness trigger) | • Trading di-halt otomatis (`HALT_NEW_TRADES`)<br>• Notifikasi Telegram CRITICAL dikirim seketika | **Operator & Director** dihubungi via telepon / emergency channel. Waktu tanggap: **< 15 menit**. |
| **P2 - HIGH** | • WebSocket disconnect gagal reconnect > 30s<br>• Orderbook depth tidak cukup berulang kali (`INSUFFICIENT_DEPTH`) | • Order baru ditolak sementara<br>• Alert Telegram HIGH dikirim | **Operator** melakukan audit konektivitas dan REST fallback. Waktu tanggap: **< 1 jam**. |
| **P3 - MEDIUM** | • Sector concentration limit tercapai (CapitalGovernor)<br>• Milestone evaluasi tercapai (10, 20 closed trades) | • Logging normal<br>• Info Telegram Milestone dikirim | Dicatat dalam log harian tanpa interupsi langsung. |

---

## 4. KEBIJAKAN MODAL FASE SOFT-LAUNCH (CAPITAL GOVERNANCE)

Berdasarkan temuan operasional V1 dan pembuktian empiris slippage:

1. **Total Alokasi Modal Fase 1**:
   * Maksimum total bankroll yang disetor ke exchange pada fase soft-launch: **Rp 500.000 s/d Rp 1.000.000**.
   * Dilarang keras menaruh modal penuh (misal Rp 10.000.000+) sebelum soft-launch menghasilkan minimal 30 closed trades live dengan Profit Factor $> 1.30$.
2. **Ukuran Posisi (Position Sizing)**:
   * Alokasi per trade: **Nominal Mikro (Rp 50.000 s/d Rp 100.000 per posisi)**.
   * Tujuan: Menguji *orderbook execution gap*, *taker fee impact*, dan *live exchange latency* tanpa menanggung risiko modal substantif.
3. **Batas Eksposur Simultan**:
   * Maksimum posisi terbuka bersamaan: **1 posisi**.
   * Maksimum eksposur portofolio: **10% dari bankroll fase soft-launch**.
