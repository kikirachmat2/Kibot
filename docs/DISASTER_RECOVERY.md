# 🆘 KIBOT V3 — DISASTER RECOVERY & RESTORE PROCEDURE

Panduan resmi pemulihan darurat (*Disaster Recovery*) jika server **SG1 (Singapore - 152.69.218.198)** mengalami kegagalan fatal, crash disk, atau harus di-provisioning ulang dari nol.

---

## 1. ARSITEKTUR BACKUP
- **Primary Database**: `/home/ubuntu/kibot_v3_data/kibot_v3.db` di SG1 (Mode WAL).
- **Offsite Backup Storage**: `/home/ubuntu/kibot_v3_backup/` di Server 2 (`213.35.118.26`).
- **Jadwal Sinkronisasi**: Otomatis tiap 6 jam via cron di Server 2 menggunakan perintah online atomic SQLite (`.backup`) melalui jaringan privat Tailscale (`100.105.139.21`).
- **File Backup Terakhir**: Selalu tersedia di Server 2 pada symlink:
  ```bash
  /home/ubuntu/kibot_v3_backup/kibot_v3.db
  ```

---

## 2. PROSEDUR RESTORE STEP-BY-STEP (UNTUK SUPERVISOR)

Jika SG1 mati total dan server baru / rebuild OS telah siap:

### Langkah 1: Siapkan Server Baru & Pastikan Prasyarat Terpasang
Login ke server SG1 baru via SSH, lalu jalankan:
```bash
sudo apt update && sudo apt install -y sqlite3 git python3-venv python3-pip chrony
sudo systemctl enable --now chrony
mkdir -p /home/ubuntu/kibot_v3_data
chmod 700 /home/ubuntu/kibot_v3_data
```

### Langkah 2: Ambil Snapshot Backup dari Server 2
Login ke **Server 2** via SSH:
```bash
ssh -i ~/.ssh/kibot/ssh-key-executor.pem ubuntu@213.35.118.26
```
Salin database backup terbaru dari Server 2 ke SG1 (bisa menggunakan IP Tailscale SG1):
```bash
scp -i ~/.ssh/id_ed25519 /home/ubuntu/kibot_v3_backup/kibot_v3.db ubuntu@100.105.139.21:/home/ubuntu/kibot_v3_data/kibot_v3.db
```

### Langkah 3: Verifikasi Integritas File di SG1 (WAJIB)
Login ke SG1 dan periksa apakah database tidak korup:
```bash
sqlite3 /home/ubuntu/kibot_v3_data/kibot_v3.db "PRAGMA integrity_check;"
```
> **Output yang diharapkan**: `ok`. Jika muncul selain `ok`, JANGAN gunakan file tersebut, gunakan snapshot bertanggal sebelumnya di `/home/ubuntu/kibot_v3_backup/kibot_v3_YYYYMMDD_HHMMSS.db`.

Periksa isi tabel positions dan events:
```bash
sqlite3 /home/ubuntu/kibot_v3_data/kibot_v3.db "SELECT * FROM positions;"
sqlite3 /home/ubuntu/kibot_v3_data/kibot_v3.db "SELECT * FROM events;"
```

### Langkah 4: Setup Codebase & Start Service
Di SG1:
```bash
cd /home/ubuntu
git clone https://github.com/kikirachmat2/KiBotV3.git
cd /home/ubuntu/KiBotV3
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Buat file .env dengan kredensial & path database
cp .env.example .env
nano .env  # Pastikan DB_PATH=/home/ubuntu/kibot_v3_data/kibot_v3.db
chmod 600 .env

# Pasang service systemd
sudo cp infra/systemd/kibot-v3-core.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kibot-v3-core.service
```

### Langkah 5: Verifikasi Status Live
Periksa status service dan cek output perintah bot:
```bash
systemctl status kibot-v3-core.service
curl -s http://127.0.0.1:8789/health
```
Lalu uji pembacaan status portofolio di Telegram bot dengan mengirim: `/status`.

---

## 3. HASIL PENGUJIAN SIMULASI RESTORE (23 SEPTEMBER 2026)
Simulasi restore telah diuji secara menyeluruh di lingkungan terisolasi:
1. Snapshot atomic diambil dari SG1 ke Server 2 (`kibot_v3_20260923_073504.db`).
2. Snapshot di-push ke direktori simulasi di SG1 (`/home/ubuntu/dr_simulation_test/`).
3. `PRAGMA integrity_check` mengembalikan hasil: **`ok`**.
4. Orchestrator membaca database hasil restore dan berhasil menampilkan posisi asli:
   - BTC: `7.459e-05` (Cost Basis Rp 105.218)
   - ETH: `0.00099602` (Cost Basis Rp 45.095)
   - NAV & PnL terhitung akurat sesuai harga live Indodax.
