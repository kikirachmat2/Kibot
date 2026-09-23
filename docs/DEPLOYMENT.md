# 🚀 KIBOT V3 — PRODUCTION DEPLOYMENT GUIDE

Panduan deployment arsitektur 2-Server untuk KiBot V3:
- **Server 1 (SG1 - Singapore: 152.69.218.198)**: Core DCA Engine, Event Ingestion, & Scheduled Telegram Reporter.
- **Server 2 (Backup / Watchdog: 213.35.118.26)**: Independent Heartbeat Watchdog, Health Monitor, & Offsite SQLite Backup.

---

## 0. Cleanup Server SG1 (Migrasi dari KiBot V2)

Sebelum memasang KiBot V3, hentikan seluruh background process dan service peninggalan V2:
```bash
# 1. Hentikan service V2 jika ada yang aktif
sudo systemctl stop kibot-v2-paper.service kibot-auto-discovery.service 2>/dev/null || true
sudo systemctl disable kibot-v2-paper.service kibot-auto-discovery.service 2>/dev/null || true

# 2. Archive direktori V2 sebelum dihapus
sudo mkdir -p /opt/kibot_archive_v2
sudo tar -czf /opt/kibot_archive_v2/kibot_v2_full_$(date +%Y%m%d).tar.gz /home/ubuntu/KiBotV2 2>/dev/null || true
ls -lh /opt/kibot_archive_v2/

# 3. Backup state files V2 (untuk audit trail)
sudo mkdir -p /opt/kibot_archive_v2/state_v2
sudo cp -r "/home/ubuntu/KiBotV2/KiBot V2/state/"* /opt/kibot_archive_v2/state_v2/ 2>/dev/null || true
ls -la /opt/kibot_archive_v2/state_v2/

# 4. Cleanup cache, vacuum journalctl, dan apt
find /home/ubuntu -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
sudo journalctl --vacuum-time=7d
sudo apt-get clean && sudo apt-get autoremove -y
df -h /

# 5. Pastikan tidak ada process Python V2 yang tertinggal
ps aux | grep -E 'kibot|python.*main' | grep -v grep
```

---

## 1. Persiapan Server & Prasyarat Sistem

### A. OS & Dependensi
- Ubuntu 22.04 LTS / 24.04 LTS
- Python 3.11+ (atau 3.14)
- `chrony` (Sangat KRITIS: sinkronisasi waktu NTP untuk mencegah Indodax API nonce error)
- `sqlite3`

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip chrony sqlite3 git
sudo systemctl enable --now chrony
chronyc tracking
```

### B. Direktori Data
```bash
mkdir -p /home/ubuntu/kibot_v3_data
chmod 700 /home/ubuntu/kibot_v3_data
```

---

## 2. Deployment Server 1 (SG1 — Core + Reporter)

### A. Clone Repository & Setup Virtualenv
```bash
cd /home/ubuntu
git clone https://github.com/kikirachmat2/KiBotV3.git
cd KiBotV3
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### B. Konfigurasi Environment (`/home/ubuntu/KiBotV3/.env`)
```bash
cp .env.example .env
chmod 600 .env
nano .env
```
Isi konfigurasi kredensial:
```ini
INDODAX_API_KEY=your_indodax_api_key_here
INDODAX_SECRET=your_indodax_api_secret_here
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
MODE=PAPER
DB_PATH=/home/ubuntu/kibot_v3_data/kibot_v3.db
API_KEY_WITHDRAWAL_DISABLED=true
```

### C. Pasang & Aktifkan Systemd Service
```bash
sudo cp infra/systemd/kibot-v3-core.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable kibot-v3-core.service
sudo systemctl start kibot-v3-core.service
sleep 5
sudo systemctl status kibot-v3-core.service --no-pager
```

### D. Verifikasi Report Terkirim
```bash
sudo journalctl -u kibot-v3-core.service -n 30 --no-pager
```

---

## 3. Deployment Server 2 (Watchdog + Backup)

### A. Clone Repository & Setup
```bash
cd /home/ubuntu
git clone https://github.com/kikirachmat2/KiBotV3.git KiBotV3-server2
cd KiBotV3-server2
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
mkdir -p /home/ubuntu/kibot_v3_backup
```

### B. Konfigurasi Environment (`/home/ubuntu/KiBotV3-server2/.env`)
```bash
# Salin dari SG1 via Tailscale
scp ubuntu@100.105.139.21:/home/ubuntu/KiBotV3/.env /home/ubuntu/KiBotV3-server2/.env
chmod 600 /home/ubuntu/KiBotV3-server2/.env
```

### C. Pasang & Aktifkan Watchdog Service
```bash
sudo cp infra/systemd/kibot-v3-watchdog.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable kibot-v3-watchdog.service
sudo systemctl start kibot-v3-watchdog.service
sudo systemctl status kibot-v3-watchdog.service --no-pager
sudo journalctl -u kibot-v3-watchdog.service -n 20 --no-pager
```

---

## 4. Validasi Pasca Deployment & Uji Interaktif Telegram

Kirim perintah interaktif ke Telegram Bot (`KukiraKikiBot`):
1. `/status` → Verifikasi snapshot NAV, saldo cash, breakdown aset, dan MODE=PAPER.
2. `/topup 500000` → Verifikasi simulasi topup Rp 500.000 dan alokasi cycle-aware aset kripto.
3. `/withdraw 100000` → Verifikasi pengurangan saldo cash dan audit basis biaya.
4. `/report` → Verifikasi trigger laporan instan komprehensif.

---

## 5. Security Checklist

Wajib dipenuhi sebelum sistem dinyatakan siap beroperasi:
- [x] **SSH Deploy Key**: Otentikasi git server menggunakan ED25519 deploy key scoped, **JANGAN** gunakan Personal Access Token (PAT).
- [x] **Indodax API Permission**: Wajib `Read=ON`, `Trade=ON`, dan `Withdrawal=OFF` (Nonaktif total).
- [x] **IP Whitelisting**: Kunci API Indodax di-whitelist secara eksplisit ke IP `152.69.218.198` (SG1) dan `213.35.118.26` (Server 2).
- [x] **File Permission**: Seluruh file `.env` di SG1 dan Server 2 berizin `chmod 600`.
- [x] **Token Telegram Rotation**: Jadwalkan rotasi token Telegram setiap 30 hari via `@BotFather`.

---

## 6. End-to-End Verification Protocol

1. **Uji Konektivitas Telegram**:
   ```bash
   curl -s https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getMe | jq .
   ```
   Pastikan HTTP return `200 OK` dengan `"is_bot": true`.
2. **Kirim Perintah Real dari Telegram Client Supervisor**:
   - Kirim `/status` dari chat admin.
   - Periksa response dalam < 30 detik (menampilkan NAV, Cash IDR, dan alokasi aset).
   - Kirim `/topup 500000`.
   - Periksa response detail eksekusi alokasi cycle-aware.
3. **Audit Log Systemd**:
   ```bash
   sudo journalctl -u kibot-v3-core.service -n 30 --no-pager
   ```
   Pastikan tidak ada exception atau error 401/403.

---

---

## 7. Pre-Launch Verification Checklist (30 September 2026)

```
PAPER TRADE PRE-LAUNCH CHECKLIST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[x] Telegram bot responds to /status via Telegram (real, bukan shell — VERIFIED LIVE)
[x] Token Telegram valid (getMe 200 OK)
[x] Token Telegram LAMA sudah revoked (getMe 401 Unauthorized)
[x] API key Indodax valid (balance query OK — Trade API 2.0 VERIFIED LIVE)
[x] API key Indodax permission: Read + Trade, NO Withdrawal (canTrade=true, canWithdraw=false)
[x] API key IP whitelist: 152.69.218.198 (SG1) & 213.35.118.26 (Server 2) — DUAL SERVER VERIFIED LIVE
[ ] PAT GitHub revoked di Settings Tokens
[x] SSH deploy key working (git pull OK di SG1 & Server 2)
[x] SG1 service kibot-v3-core running
[x] Server 2 service kibot-v3-watchdog running
[x] Harga real-time fetch dari Indodax API (cache TTL 60s)
[x] Emergency exit tested dengan simulated crash
[x] Backup state verified (SQLite WAL)
[x] Disk usage < 50%
[x] Memory usage < 80%
[x] All 60+ tests passing (60/60 tests pass)
```

---

## 8. Timeline & Protokol Paper Trade (1 - 31 Oktober 2026)

- **Mode Operasional**: `MODE=PAPER` (Virtual balance, no exchange API trade execution).
- **Periode Evaluasi**: 1 Oktober 2026 00:00 WIB s/d 31 Oktober 2026 23:59 WIB.
- **Kriteria Keberhasilan Menuju Live (1 November 2026)**:
  1. 31 Laporan Harian terkirim tepat pukul 08:00 WIB tanpa miss.
  2. 4 Laporan Mingguan terkirim setiap hari Senin 00:00 WIB.
  3. 1 Laporan Bulanan terkirim 1 November 08:00 WIB.
  4. Minimal 3 kali event simulasi `/topup` (Rp 500k, Rp 800k, Rp 1jt) dieksekusi tanpa error basis biaya.
  5. 1 kali event simulasi `/withdraw`.
  6. 0 unhandled exception atau crash restart pada service systemd.

