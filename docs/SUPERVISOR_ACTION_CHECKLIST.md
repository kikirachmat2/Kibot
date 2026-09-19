# 📋 PRE-FLIGHT CHECKLIST UNTUK SUPERVISOR

Dokumen ini memuat panduan aksi konkret yang dibutuhkan dari Supervisor untuk menjaga keamanan cluster, mengaktifkan node riset Batam, serta prosedur monitoring dan tanggap darurat harian.

---

## Section A — CANCELLED: Token Kept (Supervisor Decision)
**Status**: Dibatalkan atas keputusan Supervisor (2026-09-20). Token lama tetap dipertahankan. Chat history dinilai privat dan risiko dinilai acceptable.

Pertahanan berlapis di level kode telah aktif secara permanen sebagai mitigasi alternatif:
- ✅ **Chat ID Whitelist**: Bot hanya diizinkan mengirim ke ID chat Supervisor. Pengiriman ke ID lain di-block seketika.
- ✅ **Push-Only (No Commands)**: Bot tidak menjalankan polling (`getUpdates`) atau menerima webhook commands dari luar.
- ✅ **Sliding Rate Limit**: Dibatasi maksimal 100 pesan/jam.
- ✅ **Anomaly Burst Detection**: Jika terjadi >5 pesan dalam 60 detik, alert dikirim via jalur fallback webhook.

Tidak ada tindakan pergantian token yang diperlukan saat ini.

---

## Section B — UNTUK AKTIFKAN BATAM POLLER (Dalam 1 Minggu)
Poller Oracle Cloud ARM (2 OCPU / 12 GB RAM) di Server 2 saat ini dalam mode *quiet standby* menunggu Tailscale Auth Key agar instance Batam yang di-claim langsung tergabung ke mesh zero-trust.

- [ ] **1. Generate Tailscale Auth Key**
  - Buka browser dan login ke: [https://login.tailscale.com/admin/settings/keys](https://login.tailscale.com/admin/settings/keys)
  - Klik tombol **"Generate auth key"**.
  - Konfigurasi parameter:
    - **Reusable**: `YES` (bisa dipakai provisioning ulang)
    - **Ephemeral**: `NO`
    - **Expiration**: `90 days`
    - **Tags**: `tag:kibot` (opsional)
  - Salin kunci yang dihasilkan (format: `tskey-auth-...`).

- [ ] **2. Pasang Kunci di Server 2**
  - SSH ke Server 2:
    ```bash
    ssh -i ~/.ssh/kibot/ssh-key-executor.pem ubuntu@213.35.118.26
    sudo nano /home/ubuntu/.kibot-cluster.env
    ```
  - Masukkan kunci pada baris:
    ```bash
    TS_AUTHKEY=tskey-auth-xxxxx
    ```
  - Simpan dan keluar.

- [ ] **3. Restart Poller Batam**
  - Jalankan di Server 2:
    ```bash
    sudo systemctl restart kibot-batam-hunter.service
    ```
  - Cek log poller untuk memastikan status berburu aktif:
    ```bash
    sudo journalctl -u kibot-batam-hunter.service -f
    ```
- [ ] **4. Tunggu Notifikasi Telegram**
  - Begitu kapasitas ARM tersedia di region `ap-batam-1`, instance akan di-launch otomatis dan Telegram akan menerima alert:
    `🎉 KIBOT BATAM INSTANCE CLAIMED! Shape: 2 OCPU / 12 GB ARM`

---

## Section C — MONITORING HARIAN (5 Menit per Hari)

- [ ] **1. Cek Laporan Harian 00:00 WIB di Telegram**
  - Setiap pukul 00:00 WIB (17:00 UTC), KiBot V2 secara otomatis mengirimkan rangkuman PnL 7-hari, equity semua varian (P1-P5, Primary TF, Shadow MR), win rate, dan status open positions.
  - Jika laporan tidak masuk, periksa scheduler di SG1:
    ```bash
    sudo journalctl -u kibot-v2-paper.service -g "WeeklyReporter" -n 20 --no-pager
    ```

- [ ] **2. Cek Real-Time Health & Equity Endpoint**
  - Akses endpoint health melalui Tailscale mesh dari browser/terminal:
    ```bash
    curl -s http://100.105.139.21:8789/health | python3 -m json.tool
    ```
  - Verifikasi nilai `status == "HEALTHY"` dan `is_halted == false`.

- [ ] **3. Evaluasi Drawdown Batas Kritis**
  - Jika ada varian yang mengalami drawdown harian `> 10%` atau mingguan `> 25%`, segera hubungi Director untuk evaluasi matriks korelasi dan regime gate.

---

## Section D — RUNBOOK DARURAT (EMERGENCY PLAYBOOK)

### 1. Bot atau Service Terhenti (Down)
Jika service `kibot-v2-paper.service` tidak berjalan di SG1:
```bash
ssh -i ~/.ssh/manake_singapore ubuntu@152.69.218.198
sudo systemctl restart kibot-v2-paper.service
sudo journalctl -u kibot-v2-paper.service -f
```

### 2. Token Telegram Bocor / Diduga Compromised
Segera jalankan instruksi di **Section A**:
1. Buka `@BotFather` -> `/revoke`.
2. Perbarui `.env` di SG1 dan `.kibot-cluster.env` di Server 2.
3. Restart kedua service.

### 3. Batam Poller Stuck atau Mengalami Error
Periksa log eksekusi poller di Server 2:
```bash
ssh -i ~/.ssh/kibot/ssh-key-executor.pem ubuntu@213.35.118.26
sudo journalctl -u kibot-batam-hunter.service -n 50 --no-pager
```
Jika ada error konfigurasi OCI API, periksa permission file `batam.pem` (harus `600`) dan validity OCID.

### 4. Deadman Switch Terpicu Tak Terduga
Jika koneksi internet SG1 terputus lebih dari 15 menit, Indodax Deadman Switch akan mengeksekusi `countdownCancelAll` dan membatalkan seluruh limit order aktif di akun Indodax:
1. Login ke web Indodax, verifikasi status Open Orders.
2. Cek log Deadman di SG1:
   ```bash
   sudo journalctl -u kibot-v2-paper.service -g "Deadman" -n 50 --no-pager
   ```
3. Restart `kibot-v2-paper.service` untuk re-synchronize order ledger dan re-arm countdown timer ke Indodax.

---

## Section E — MONITORING DATA INTEGRITY (HARIAN)
Menjaga konsistensi kalkulasi state dan ledger agar metrik performa selalu akurat:

- [ ] **1. Cek Equity P1–P5 di Health Endpoint**
  - Akses `curl -s http://100.105.139.21:8789/health | jq .paper_p1_p4_summary`
- [ ] **2. Deteksi Anomali Variasi Cepat**
  - Kalau ada variasi equity `> 5%` dalam 1 jam tanpa ada trade closed (`closed_trades == 0`) → **SEGERA LAPOR KE DIRECTOR**.
- [ ] **3. Cek Rasio Equity P1/P2/P3**
  - Equity P1, P2, dan P3 harus berkisar di rentang yang mirip (perbedaan wajar hanya dari spread/TP level, tidak boleh ada lonjakan 2x lipat mendadak).
- [ ] **4. Cek Equity PRIMARY_TF**
  - Pastikan equity `PRIMARY_TF` wajar (tidak crash `> 50%` dalam 1 hari tanpa perubahan drastis di harga pasar koin yang di-hold).
- [ ] **5. Review Dokumen SECURITY_INCIDENT Setiap 30 Hari**
  - Jadwal review berikutnya: **2026-10-20**. Verifikasi apakah token lama masih aman dan tidak ada indikasi aktivitas anomali.
- [ ] **6. Tanggap Darurat Token Abuse**
  - Jika sewaktu-waktu ditemukan indikasi token abuse (pesan asing dari bot), lakukan revoke seketika via `@BotFather` -> `/revoke`.
- [ ] **7. Audit BotFather Tiap 7 Hari**
  - Cek `@BotFather` → bot settings tiap 7 hari. Pastikan tidak ada activity mencurigakan.
- [ ] **8. Deteksi Outbound Tak Dikenal**
  - Kalau ada notif Telegram ke chat lain yang Anda tidak kenal → revoke token immediately, jangan tunggu 30 hari.


