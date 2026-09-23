# ARSITEKTUR & DESAIN: 3-NODE MONITORING CLUSTER (SG1 - SERVER 2 - BATAM)

Dokumen ini mendefinisikan spesifikasi desain teknis untuk monitoring cluster 3-node KiBot V3.
**Catatan Penting:** Dokumen ini merupakan blueprint desain siap pakai begitu server Batam aktif. **TIDAK ADA** kode baru atau dependensi yang diaktifkan sebelum server Batam siap.

---

## 1. Topologi Jaringan & Isolasi Keamanan

- **Zero Public Exposure:** Seluruh interaksi monitoring dan sinkronisasi data antar node berjalan **100% di dalam private mesh network Tailscale (100.x.x.x)**.
- **Firewall Policy:**
  - Port `/health` SG1 (`8789`) **DILARANG** dibuka ke internet publik (`0.0.0.0/0`).
  - Tidak ada rule `iptables` publik baru yang ditambahkan ke SG1.
  - Port hanya dapat diakses oleh node yang terautentikasi dalam Tailnet yang sama (SG1, Server 2, dan Node Batam).

```
                 +-----------------------------------+
                 |        SUPERVISOR TELEGRAM        |
                 +-----------------+-----------------+
                                   ^
            Jalur 1: Bot Utama     |     Jalur 2 & 3: Bot Watchdog / Batam
      (Laporan Harian/Mingguan)    |     (Alert Kritis Independen)
                                   |
         +-------------------------+-------------------------+
         |                                                   |
+--------+--------+      +-------------------+      +--------+--------+
|      SG1        |      |     SERVER 2      |      |     BATAM       |
| (Trading Core)  |<====>|  (Local Witness)  |<====>| (Off-Cloud OOB) |
| 100.105.139.21  |      |   213.35.118.26   |      |  (Tailscale IP) |
+-----------------+      +-------------------+      +-----------------+
         |                         |                         |
         +-------------------------+-------------------------+
                         Tailscale Mesh VPN (100.x.x.x)
```

---

## 2. Peran & Tanggung Jawab Masing-Masing Node

| Node | Lokasi / Infrastruktur | Peran Utama | Polling Interval | Jalur Notifikasi |
| :--- | :--- | :--- | :--- | :--- |
| **SG1** | Oracle Cloud Singapore | Core Execution (Pure Buy-Only DCA, Poller Indodax, Telegram Commands) | 180s balance poll | Bot Utama (`TELEGRAM_BOT_TOKEN`) |
| **Server 2** | Oracle Cloud Singapore (AD terpisah) | Witness Watchdog + SQLite Backup Sync harian | 60s ping ke SG1 | Bot Watchdog (`WATCHDOG_TELEGRAM_BOT_TOKEN`) |
| **Batam** | Non-Oracle Infrastructure (Batam Node) | **Independent Out-of-Band Sentinel**: Pengawas independen dari luar Oracle Cloud | 120s ping ke SG1 & Server 2 | Dedicated Batam Bot (`BATAM_TELEGRAM_BOT_TOKEN`) |

---

## 3. Mekanisme Kerja Batam Sentinel

Begitu server Batam aktif dan terhubung ke Tailscale:

1. **Dual-Node Health Polling:**
   - Batam melakukan HTTP GET ke `http://100.105.139.21:8789/health` (SG1).
   - Batam melakukan ping / status probe ke Server 2 via Tailscale.
2. **Aturan Deteksi Kegagalan:**
   - Jika SG1 gagal merespons **>= 3x berturut-turut** (6 menit): Batam memverifikasi apakah Server 2 juga melihat SG1 mati.
   - **Kasus A (SG1 mati, Server 2 hidup):** Server 2 mengeksekusi restart otomatis via SSH lokal; Batam bertindak sebagai second opinion alert jika Server 2 gagal restart.
   - **Kasus B (SG1 dan Server 2 mati bersamaan — misal outage region Oracle Singapore):** Batam **LANGSUNG** menembakkan alert darurat ke Telegram Supervisor:
     ```
     🚨 BATAM SENTINEL ALERT: ORACLE REGION OUTAGE DETECTED!
     • SG1 (100.105.139.21): UNREACHABLE
     • Server 2: UNREACHABLE
     • Waktu: [Timestamp WIB]
     ⛔ Kedua node Oracle Cloud tidak merespons via Tailscale. Kemungkinan gangguan jaringan / datacenter Singapore.
     ```
3. **Independensi Kredensial:**
   - Node Batam menggunakan token Telegram tersendiri (`BATAM_TELEGRAM_BOT_TOKEN`).
   - Jika token bot utama di SG1 bermasalah, Batam tetap bisa mengirim kabar ke Supervisor.

---

## 4. Checklist Aktivasi Saat Server Batam Tersedia

1. Install Tailscale di server Batam dan hubungkan ke Tailnet yang sama (`tailscale up`).
2. Clone repo `KiBotV3` di Batam.
3. Siapkan file `.env` di Batam dengan bot token baru dari `@BotFather`.
4. Jalankan script sentinel Batam via systemd service.
