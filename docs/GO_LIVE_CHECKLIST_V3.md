# 🚦 KIBOT V3 — GO-LIVE AUDIT & APPROVAL CHECKLIST

> [!IMPORTANT]
> **PERATURAN MUTLAK:**
> Bot saat ini berjalan dalam **`MODE=PAPER`**. Pengubahan konfigurasi ke **`MODE=LIVE`** di server manapun dilarang keras sampai **SETIAP POIN** di bawah ini diverifikasi dan disetujui eksplisit oleh Supervisor.

---

## DAFTAR KRITERIA KELAYAKAN GO-LIVE

### [ ] 1. Observasi Paper Trading Minimal 3 Hari Tanpa Crash
- [ ] Bot berjalan stabil terus-menerus di SG1 selama minimal 72 jam sejak reset observasi (Target: 23 September – 26 September 2026).
- [ ] Tidak ada unhandled exception, OOM kill, atau crash restart di `journalctl -u kibot-v3-core.service`.
- [ ] Endpoint `/health` via Tailscale merespons `HEALTHY` secara konsisten dengan `consecutive_poll_failures = 0`.
- [ ] Terjadi minimal 1x siklus penuh end-to-end: topup simulasi/deteksi -> alokasi 70/30 -> tercatat di SQLite -> tampil akurat di `/status` dan laporan harian Telegram 08:00 WIB.

---

### [ ] 2. Smoke-Test HMAC & API Indodax Nyata (Read-Only)
- [ ] Lakukan smoke-test koneksi API Indodax menggunakan kredensial asli (`API_KEY` dan `SECRET_KEY`) **HANYA untuk endpoint read-only**:
  - `getInfo` (cek saldo akun dan kuota API).
  - Validasi nonce, perhitungan signature HMAC-SHA512, dan sinkronisasi jam NTP chrony.
- [ ] **DILARANG** memanggil endpoint transaksi (`trade` / `place_buy_order`) selama tahap smoke-test ini.

---

### [ ] 3. Konfigurasi Batas Modal Personal Supervisor di `.env`
Supervisor menentukan batas keamanan finansial pribadi (bukan nilai default sistem):
- [ ] **`MAX_SINGLE_TRADE_IDR`**: Disetel sesuai konfirmasi Supervisor (misal: Rp 1.000.000 atau nominal lain yang disetujui).
- [ ] **`MAX_MONTHLY_TOPUP_IDR`**: Disetel sesuai plafon bulanan Supervisor (misal: Rp 5.000.000 atau nominal lain yang disetujui).
- [ ] Nilai guardrail terverifikasi aktif dan diuji coba tidak bisa dibobol oleh topup yang melebihi batas.

---

### [ ] 4. Audit Keamanan Kredensial & Riwayat Token
- [ ] Bot token Telegram aktif dan API credentials tidak pernah muncul dalam command shell, log git, atau transcript publik.
- [ ] Token Telegram watchdog terpisah dari token Telegram bot utama.
- [ ] `.env` di SG1 memiliki permission ketat (`chmod 600 /home/ubuntu/KiBotV3/.env`).

---

### [ ] 5. Audit Eksposur Repositori Publik GitHub
- [ ] Konfirmasi git tree bersih: `git status` tidak memiliki file `.env`, database `.db`, atau secret yang ter-track.
- [ ] Jalankan script audit lokal `python3 scripts/check_secrets.py` dan pastikan hasil return `0 matches found`.

---

### [ ] 6. Status Node Cadangan & Monitoring Multi-Server
- [ ] **Server 2 (Backup / Watchdog: 213.35.118.26)**:
  - Service `kibot-v3-watchdog.service` aktif dan berhasil melakukan ping berkala ke endpoint Tailscale SG1 (`100.105.139.21:8789/health`).
  - SSH key Server 2 -> SG1 terpasang dengan NOPASSWD sudoers terbatas hanya untuk `systemctl restart kibot-v3-core`.
  - Sinkronisasi backup database harian offsite aktif.
- [ ] **Node Batam (Oracle Cloud)**:
  - *Status*: **Nice-to-Have (Bukan Blocker Wajib)**.
  - Jika instance Batam sudah aktif, monitoring 3-node dipasang; jika belum aktif, cluster 2-node (SG1 + Server 2) diizinkan untuk live trading.

---

## FORMULIR PERSETUJUAN SUPERVISOR

Setelah seluruh 6 kriteria di atas diverifikasi, Supervisor mengisi persetujuan akhir di bawah ini sebelum `.env` diubah ke `MODE=LIVE`:

- **Tanggal Review**: `____________________`
- **Plafon Max Trade Disetujui**: `Rp ________________`
- **Plafon Max Bulanan Disetujui**: `Rp ________________`
- **Tanda Tangan / Konfirmasi Approval**: `[ APPROVED / NOT APPROVED ]`
