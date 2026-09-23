# OPERATIONAL RESILIENCE & ACCEPTED RISKS — KIBOT V3

Dokumen ini mencatat kebijakan ketahanan operasional, audit berkala, dan **ACCEPTED RISKS** (risiko yang diterima secara sadar) untuk sistem KiBot V3 yang beroperasi tanpa pantauan aktif dalam jangka panjang.

---

## 1. Non-Negotiable Operational Guardrails

Sistem diproteksi dengan batasan deterministik yang tidak dapat dilanggar secara otomatis:
1. **MAX_SINGLE_TRADE_IDR (Rp 1.000.000):**
   - Setiap transaksi topup atau eksekusi tunggal di atas Rp 1.000.000 **otomatis ditolak**.
   - Sistem TIDAK memotong secara diam-diam (silent clipping) dan TIDAK gagal diam-diam.
   - Mengirim alert eskalasi instan via Telegram ke Supervisor.
2. **MAX_MONTHLY_TOPUP_IDR (Rp 5.000.000):**
   - Agregasi pengeluaran bulanan dihitung langsung dari tabel SQLite `transactions`.
   - Jika topup baru menyebabkan total bulanan melebihi Rp 5.000.000, transaksi **ditolak total**.
3. **Stale Price Protection (10 Menit):**
   - Dalam mode Live, jika harga pasar Indodax berasal dari cache yang lebih tua dari 600 detik (10 menit), bot menolak mengeksekusi order buy.
4. **Consecutive Failure Escalation (5x Berturut-Turut):**
   - Polling saldo, poller Telegram, dan scheduler yang gagal >= 5x berturut-turut mengirimkan alert eskalasi kritis ke Telegram.
   - Dilengkapi rate-limit pengiriman ulang maksimal tiap 6 jam untuk mencegah spam alert namun tetap menjamin awareness.

---

## 2. ACCEPTED RISK: Oracle Cloud Always Free Idle Reclamation

### Deskripsi Risiko
- Instance Oracle Cloud Infrastructure (OCI) berstatus *Always Free* memiliki kebijakan otomatisasi reklamasi (reclaim policy) jika mesin dianggap menganggur (*idle*) selama 7 hari berturut-turut (utilisasi CPU 95th percentile < 15-20%, bandwidth < 15-20%).
- Ketika direclaim, instance akan di-*STOP* (dimatikan). Data di boot volume tetap ada, namun service bot terhenti sampai instance dinyalakan kembali secara manual via Oracle Console.

### Keputusan Supervisor
- **Keputusan:** Risiko ini **DITERIMA APA ADANYA (ACCEPTED RISK)**.
- **Batasan Kebijakan:**
  - Tidak melakukan upgrade akun ke PAYG (Pay-As-You-Go).
  - **DILARANG KERAS** menggunakan trik teknis seperti cron CPU-burner / artificial load gaming untuk mengelabui deteksi idle Oracle (berisiko melanggar Terms of Service dan menyebabkan penangguhan akun permanen).

### Jaring Pengaman Manual (Legitimate Human Safety Net)
- KiBot V3 menyertakan reminder pemeliharaan otomatis dalam **Laporan Audit Bulanan (setiap tanggal 1 pukul 08:00 WIB)**:
  ```
  🛡️ REMINDER PEMELIHARAAN INFRASTRUKTUR BULANAN:
  • Silakan login ke Oracle Cloud Console dan verifikasi SG1 & Server 2 masih aktif (Running).
  • Cek status & disk space untuk memastikan instans Always Free tetap aman.
  ```
- Supervisor meluangkan waktu 1 menit setiap awal bulan untuk memeriksa status instance di console web Oracle.

---

## 3. Network & Health Isolation Policy

1. **Tailscale Only:**
   - Port `/health` SG1 (`8789`) dan seluruh port komunikasi cluster **HANYA** boleh diakses melalui interface Tailscale (IP `100.x.x.x`).
   - Port 8789 **TIDAK PERNAH** diexpose ke internet publik (`0.0.0.0/0`) via iptables.
2. **Watchdog Server 2:**
   - Melakukan polling health endpoint SG1 via Tailscale.
   - Memiliki token Telegram independen (`WATCHDOG_TELEGRAM_BOT_TOKEN`).
   - Berhak melakukan restart service SG1 via SSH key jika missed pings >= 3x.
